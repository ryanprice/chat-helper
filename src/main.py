import asyncio
import logging
import sys
from typing import Optional

from src.agent import Agent
from src.base_agent import _wrap
from src.config import Settings
from src.models import InboundMessage
from src.ollama_client import OllamaClient
from src.signal_client import SignalClient
from src.watcher import WatcherAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# Registry of all active asyncio tasks — used by the kill switch.
_active_tasks: set[asyncio.Task] = set()


def _track(coro) -> asyncio.Task:
    """Create a task and add it to the active-task registry."""
    task = asyncio.create_task(coro)
    _active_tasks.add(task)
    task.add_done_callback(_active_tasks.discard)
    return task


def _is_kill_command(msg: InboundMessage, settings: Settings) -> bool:
    """Return True if the owner sent the kill-switch word."""
    if msg.source_number != settings.signal_phone_number:
        return False
    return msg.message_text.strip().lower() in ("kkk", "/kkk")


async def _handle_kill(sender: SignalClient, settings: Settings) -> None:
    """Cancel all active tasks and notify the owner."""
    count = len(_active_tasks)
    for task in list(_active_tasks):
        task.cancel()
    _active_tasks.clear()
    logger.warning("Kill switch activated — cancelled %d task(s)", count)
    try:
        await sender.send_message(
            _wrap(f"🛑 Kill switch: {count} active task(s) cancelled."),
            recipient_number=settings.signal_phone_number,
        )
    except Exception as e:
        logger.error("Failed to send kill-switch confirmation: %s", e)


async def main() -> None:
    settings = Settings.from_env()
    logger.info(
        "Starting chat-helper | number=%s model=%s watcher=%s",
        settings.signal_phone_number,
        settings.ollama_model,
        settings.watcher_enabled,
    )

    sender = SignalClient(settings)
    ollama = OllamaClient(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        tool_use_fallback=settings.tool_use_fallback,
    )
    agent = Agent(settings=settings, sender=sender, ollama=ollama)
    watcher: Optional[WatcherAgent] = (
        WatcherAgent(settings=settings, sender=sender, ollama=ollama)
        if settings.watcher_enabled
        else None
    )

    if watcher:
        logger.info("WatcherAgent enabled (batch=%d, cooldown=%ds)",
                    settings.watcher_batch_size, settings.watcher_cooldown_seconds)

    try:
        async for msg in sender.listen():
            # Kill switch — owner-only, bypasses everything else.
            if _is_kill_command(msg, settings):
                _track(_handle_kill(sender, settings))
                continue

            _track(agent.handle_message(msg))
            if watcher:
                _track(watcher.observe(msg))
    finally:
        await sender.aclose()
        await ollama.aclose()


if __name__ == "__main__":
    asyncio.run(main())
