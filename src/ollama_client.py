import json
import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class OllamaClient:
    def __init__(self, base_url: str, model: str, tool_use_fallback: bool = False):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._tool_use_fallback = tool_use_fallback
        self._client = httpx.AsyncClient(timeout=120.0)

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> dict[str, Any]:
        """Send a chat request to Ollama and return the parsed response message."""
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools

        response = await self._client.post(
            f"{self._base_url}/api/chat",
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        message = data.get("message", {})

        # If the model returned tool_calls natively, we're done.
        if message.get("tool_calls"):
            return message

        # Fallback: parse <tool_call>{...}</tool_call> tags from text content.
        if self._tool_use_fallback and message.get("content"):
            tool_calls = _parse_tool_calls_from_text(message["content"])
            if tool_calls:
                message["tool_calls"] = tool_calls

        return message

    async def aclose(self) -> None:
        await self._client.aclose()


def _parse_tool_calls_from_text(text: str) -> list[dict]:
    """Extract tool calls embedded as <tool_call>{...}</tool_call> in model output."""
    pattern = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)
    tool_calls = []
    for match in pattern.finditer(text):
        raw = match.group(1).strip()
        try:
            data = json.loads(raw)
            tool_calls.append(
                {
                    "function": {
                        "name": data.get("name", ""),
                        "arguments": data.get("arguments", {}),
                    }
                }
            )
        except json.JSONDecodeError:
            logger.warning("Failed to parse tool_call JSON: %s", raw)
    return tool_calls
