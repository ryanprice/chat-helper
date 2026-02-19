import asyncio
import logging
import sys

from src.config import Settings
from src.agent import Agent
from src.ollama_client import OllamaClient
from src.signal_client import SignalClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = Settings.from_env()
    logger.info(
        "Starting chat-helper | number=%s model=%s",
        settings.signal_phone_number,
        settings.ollama_model,
    )

    sender = SignalClient(settings)
    ollama = OllamaClient(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        tool_use_fallback=settings.tool_use_fallback,
    )
    agent = Agent(settings=settings, sender=sender, ollama=ollama)

    try:
        async for msg in sender.listen():
            asyncio.create_task(agent.handle_message(msg))
    finally:
        await sender.aclose()
        await ollama.aclose()


if __name__ == "__main__":
    asyncio.run(main())
