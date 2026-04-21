import json
import logging
import time
from collections import deque
from typing import Optional
from uuid import uuid4

from src.base_agent import BaseAgent, _wrap
from src.config import Settings
from src.feedback import FeedbackLog
from src.models import InboundMessage
from src.ollama_client import OllamaClient
from src.signal_client import SignalClient

logger = logging.getLogger(__name__)

_DECISION_SYSTEM_TEMPLATE = """\
You are a passive Signal chat monitor. Review the recent conversation and decide if autonomous action is warranted.

Action types:
- research: A factual question was asked that could be answered with a web search
- summarize: A long or information-dense thread could benefit from a summary
- classify: A message seems urgent, time-sensitive, or needs routing attention
- execute: A goal was stated that requires multi-step tool use to accomplish

Feedback history (what the owner found useful vs not):
{feedback_summary}

Rules:
- Default to NOT acting. Only act when there is clear, specific value.
- Do not act on casual conversation, greetings, or messages already handled by slash commands.
- Return JSON only: {{"act": true/false, "action_type": "research|summarize|classify|execute", "reason": "one sentence"}}
"""

_ACTION_SYSTEMS = {
    "research": (
        "You are a research assistant monitoring a Signal chat. A question was asked. "
        "Search the web to find a concise, accurate answer and report it to the owner."
    ),
    "summarize": (
        "You are a summarization assistant monitoring a Signal chat. "
        "Summarize the recent conversation thread into key points for the owner."
    ),
    "classify": (
        "You are a message classifier monitoring a Signal chat. "
        "Classify the urgency and nature of the recent messages and report to the owner."
    ),
    "execute": (
        "You are an autonomous assistant monitoring a Signal chat. "
        "A goal or task was stated. Use available tools to accomplish it and report results to the owner."
    ),
}


class WatcherAgent(BaseAgent):
    def __init__(self, settings: Settings, sender: SignalClient, ollama: OllamaClient):
        super().__init__(settings, sender, ollama)
        self._chat_buffers: dict[str, deque] = {}
        self._last_action_time: dict[str, float] = {}
        self._message_counts: dict[str, int] = {}
        self._feedback_log = FeedbackLog()

    async def observe(self, msg: InboundMessage) -> None:
        """Main entry point — called for every inbound message."""
        if await self._check_feedback(msg):
            return

        if not self._should_observe(msg):
            return

        chat_id = self._get_chat_id(msg)
        self._add_to_buffer(chat_id, msg)

        # Accumulate batch_size messages before firing the decision gate
        self._message_counts[chat_id] = self._message_counts.get(chat_id, 0) + 1
        if self._message_counts[chat_id] < self._settings.watcher_batch_size:
            return

        self._message_counts[chat_id] = 0

        if self._in_cooldown(chat_id):
            logger.debug("Watcher cooldown active for chat %s", chat_id)
            return

        decision = await self._decision_gate(chat_id)
        if decision is None or not decision.get("act"):
            return

        action_type = decision.get("action_type", "research")
        reason = decision.get("reason", "")
        context_messages = list(self._chat_buffers.get(chat_id, []))

        self._last_action_time[chat_id] = time.monotonic()
        await self._act(chat_id, action_type, reason, context_messages)

    async def _check_feedback(self, msg: InboundMessage) -> bool:
        """If owner sends /fb 0 or /fb 1, record feedback and return True."""
        if msg.source_number != self._settings.signal_phone_number:
            return False

        text = msg.message_text.strip().lower()
        if text not in ("/fb 0", "/fb 1"):
            return False

        score = int(text[-1])
        entry = self._feedback_log.get_last_unrated()

        if entry is None:
            await self._sender.send_message(
                _wrap("No unrated watcher action found."),
                recipient_number=self._settings.signal_phone_number,
            )
            return True

        action_id = entry.get("action_id", "?")
        self._feedback_log.update_score(action_id, score)
        label = "useful" if score == 1 else "not useful"
        await self._sender.send_message(
            _wrap(f"Feedback recorded: action {action_id} marked as {label}."),
            recipient_number=self._settings.signal_phone_number,
        )
        logger.info("Feedback %d recorded for action %s", score, action_id)
        return True

    def _get_chat_id(self, msg: InboundMessage) -> str:
        if msg.group_info:
            return f"group:{msg.group_info.group_id}"
        return f"dm:{msg.source_number}"

    def _add_to_buffer(self, chat_id: str, msg: InboundMessage) -> None:
        if chat_id not in self._chat_buffers:
            self._chat_buffers[chat_id] = deque(maxlen=self._settings.watcher_context_window)
        self._chat_buffers[chat_id].append({
            "sender": msg.source_name or msg.source_number,
            "text": msg.message_text,
            "timestamp": msg.timestamp,
        })

    def _should_observe(self, msg: InboundMessage) -> bool:
        text = msg.message_text.strip()
        if len(text) < 8:
            return False
        # Skip slash commands — already handled by Agent
        first_token = text.split()[0] if text else ""
        if first_token.startswith("/"):
            return False
        # Skip messages the bot itself sent (syncMessages with no destination are outbound)
        if msg.source_number == self._settings.signal_phone_number and msg.destination_number is None:
            return False
        return True

    def _in_cooldown(self, chat_id: str) -> bool:
        last = self._last_action_time.get(chat_id)
        if last is None:
            return False
        return (time.monotonic() - last) < self._settings.watcher_cooldown_seconds

    async def _decision_gate(self, chat_id: str) -> Optional[dict]:
        """Lightweight LLM call to decide whether to act. Returns parsed JSON or None."""
        buffer = self._chat_buffers.get(chat_id)
        if not buffer:
            return None

        feedback_summary = self._feedback_log.summarize()
        system = _DECISION_SYSTEM_TEMPLATE.format(feedback_summary=feedback_summary)
        serialized = "\n".join(f"[{m['sender']}]: {m['text']}" for m in buffer)
        user_text = f"Recent messages in this chat:\n{serialized}"

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ]

        try:
            response = await self._ollama.chat(messages, tools=None)
            content = response.get("content", "").strip()
            logger.debug("Decision gate for %s: %s", chat_id, content)

            # Strip markdown code fences if the model wraps the JSON
            if content.startswith("```"):
                content = content.split("\n", 1)[-1]
                content = content.rsplit("```", 1)[0].strip()

            return json.loads(content)
        except Exception as e:
            logger.warning("Decision gate failed for %s: %s", chat_id, e)
            return None

    async def _act(
        self,
        chat_id: str,
        action_type: str,
        reason: str,
        context_messages: list[dict],
    ) -> None:
        action_id = f"w-{uuid4().hex[:6]}"
        system_prompt = _ACTION_SYSTEMS.get(action_type, _ACTION_SYSTEMS["research"])
        serialized = "\n".join(f"[{m['sender']}]: {m['text']}" for m in context_messages)
        user_text = f"Context: {reason}\n\nRecent conversation:\n{serialized}"
        trigger_summary = (reason[:120] if reason else f"{action_type} in {chat_id}")

        self._feedback_log.record(action_id, chat_id, action_type, trigger_summary)

        try:
            result = await self._tool_loop(system_prompt, user_text)
        except Exception as e:
            logger.error("Watcher _act tool loop failed: %s", e)
            result = f"(Tool loop error: {e})"

        await self._report_to_owner(result, action_id, action_type, reason)

    async def _report_to_owner(
        self,
        text: str,
        action_id: str,
        action_type: str,
        reason: str,
    ) -> None:
        header = f"👁 Watcher ({action_type}): {reason}\n\n"
        footer = f"\n\n[ID: {action_id}] · /fb 1 useful · /fb 0 not"
        wrapped = _wrap(header + text + footer)
        await self._sender.send_message(
            wrapped,
            recipient_number=self._settings.signal_phone_number,
        )
        logger.info("Watcher report sent to owner (action=%s, type=%s)", action_id, action_type)
