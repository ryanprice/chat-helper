import json
import logging
from typing import Any

from src.config import Settings
from src.ollama_client import OllamaClient
from src.signal_client import SignalClient
from src.tools import TOOL_DEFINITIONS, TOOL_REGISTRY

logger = logging.getLogger(__name__)

_BORDER = "〔🤖 chat-helper〕" + "━" * 16


def _wrap(text: str) -> str:
    """Frame any agent-generated message so it's clearly identifiable in chat."""
    return f"{_BORDER}\n{text}\n{'━' * 34}"


class BaseAgent:
    def __init__(self, settings: Settings, sender: SignalClient, ollama: OllamaClient):
        self._settings = settings
        self._sender = sender
        self._ollama = ollama

    async def _tool_loop(self, system_prompt: str, user_text: str) -> str:
        """Run the agentic tool loop and return the final text response."""
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ]

        for _iteration in range(self._settings.max_tool_iterations):
            response = await self._ollama.chat(messages, tools=TOOL_DEFINITIONS)

            tool_calls = response.get("tool_calls")
            if not tool_calls:
                return response.get("content", "").strip()

            messages.append({"role": "assistant", **response})

            for call in tool_calls:
                func = call.get("function", {})
                name = func.get("name", "")
                args = func.get("arguments", {})

                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}

                tool_fn = TOOL_REGISTRY.get(name)
                if tool_fn is None:
                    result = f"Unknown tool: {name}"
                    logger.warning("Unknown tool called: %s", name)
                else:
                    try:
                        result = await tool_fn(**args)
                        logger.debug("Tool %s(%s) returned %d chars", name, args, len(result))
                    except Exception as e:
                        result = f"Tool error: {e}"
                        logger.error("Tool %s failed: %s", name, e)

                messages.append({"role": "tool", "content": result, "name": name})

        logger.warning("Max tool iterations reached, doing final call without tools")
        final = await self._ollama.chat(messages, tools=None)
        return final.get("content", "").strip()
