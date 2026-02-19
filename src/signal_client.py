import asyncio
import json
import logging
from typing import AsyncIterator, Optional
from urllib.parse import quote as url_quote

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

from src.config import Settings
from src.models import GroupInfo, InboundMessage, Quote

logger = logging.getLogger(__name__)

_IGNORED_TYPES = {"typingMessage", "receiptMessage"}


def parse_envelope(raw: dict) -> Optional[InboundMessage]:
    """Parse a raw WebSocket envelope dict into an InboundMessage, or None to ignore."""
    envelope = raw.get("envelope", {})

    # Ignore non-data message types
    for ignored in _IGNORED_TYPES:
        if ignored in envelope:
            return None

    # When the bot owner sends a command from their own phone, signal-cli
    # receives a syncMessage (copy of sent message) rather than a dataMessage.
    # Extract sentMessage from syncMessage so those commands are also handled.
    is_sync = False
    data_message = envelope.get("dataMessage")
    if data_message is None:
        data_message = envelope.get("syncMessage", {}).get("sentMessage")
        is_sync = data_message is not None

    if not data_message:
        return None

    message_text = data_message.get("message", "")
    if not message_text or not message_text.strip():
        return None

    source_number = envelope.get("sourceNumber", "")
    source_name = envelope.get("sourceName", "")
    timestamp = envelope.get("timestamp", 0)

    # Parse optional quote
    quote: Optional[Quote] = None
    raw_quote = data_message.get("quote")
    if raw_quote:
        quote = Quote(
            author_number=raw_quote.get("authorNumber", ""),
            text=raw_quote.get("text", ""),
            timestamp=raw_quote.get("id", 0),
        )

    # Parse optional group info
    group_info: Optional[GroupInfo] = None
    raw_group = data_message.get("groupInfo")
    if raw_group:
        group_info = GroupInfo(
            group_id=raw_group.get("groupId", ""),
            group_type=raw_group.get("type", ""),
        )

    destination_number: Optional[str] = None
    if is_sync:
        raw_dest = data_message.get("destinationNumber") or data_message.get("destinationUuid")
        if raw_dest:
            destination_number = raw_dest

    return InboundMessage(
        source_number=source_number,
        source_name=source_name,
        message_text=message_text,
        timestamp=timestamp,
        group_info=group_info,
        quote=quote,
        destination_number=destination_number,
    )


class SignalClient:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._http = httpx.AsyncClient(timeout=30.0)
        self._headers = {}
        if settings.signal_api_token:
            self._headers["Authorization"] = f"Bearer {settings.signal_api_token}"

    def _ws_url(self) -> str:
        base = self._settings.signal_api_url
        # Convert http(s):// to ws(s)://
        base = base.replace("http://", "ws://").replace("https://", "wss://")
        number = url_quote(self._settings.signal_phone_number, safe="")
        return f"{base}/v1/receive/{number}"

    async def listen(self) -> AsyncIterator[InboundMessage]:
        """Yield parsed InboundMessages from the Signal WebSocket, reconnecting on error."""
        delay = 1
        while True:
            try:
                ws_url = self._ws_url()
                logger.info("Connecting to Signal WebSocket: %s", ws_url)
                async with websockets.connect(
                    ws_url,
                    additional_headers=self._headers,
                    ping_interval=30,
                    ping_timeout=10,
                ) as ws:
                    delay = 1  # reset backoff on successful connection
                    logger.info("Connected to Signal WebSocket")
                    async for raw_text in ws:
                        try:
                            raw = json.loads(raw_text)
                        except json.JSONDecodeError:
                            logger.warning("Non-JSON message received: %s", raw_text[:200])
                            continue

                        # Log envelope type only — never log message content
                        envelope_keys = list(raw.get("envelope", {}).keys())
                        logger.debug("Envelope received, keys: %s", envelope_keys)
                        msg = parse_envelope(raw)
                        if msg is not None:
                            yield msg

            except ConnectionClosed as e:
                logger.warning("WebSocket closed: %s. Reconnecting in %ds…", e, delay)
            except Exception as e:
                logger.error("WebSocket error: %s. Reconnecting in %ds…", e, delay)

            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)

    async def send_message(self, text: str, recipient_number: str) -> None:
        """Send a DM to recipient_number via the Signal REST API."""
        url = f"{self._settings.signal_api_url}/v2/send"
        payload = {
            "number": self._settings.signal_phone_number,
            "recipients": [recipient_number],
            "message": text,
        }
        response = await self._http.post(url, json=payload, headers=self._headers)
        response.raise_for_status()
        logger.info("Sent DM to %s", recipient_number)

    async def send_to_chat(self, text: str, msg: "InboundMessage") -> None:
        """Send a message back to the originating chat (group or individual DM)."""
        url = f"{self._settings.signal_api_url}/v2/send"
        payload: dict = {
            "number": self._settings.signal_phone_number,
            "message": text,
        }
        if msg.group_info:
            payload["groupId"] = msg.group_info.group_id
            logger.info("Sending to group %s", msg.group_info.group_id)
        elif msg.destination_number:
            # Sync 1:1 DM — destination_number is the other person in the conversation
            payload["recipients"] = [msg.destination_number]
            logger.info("Sending to 1:1 chat destination %s", msg.destination_number)
        else:
            payload["recipients"] = [msg.source_number]
            logger.info("Sending to source %s (fallback)", msg.source_number)
        response = await self._http.post(url, json=payload, headers=self._headers)
        response.raise_for_status()

    async def aclose(self) -> None:
        await self._http.aclose()
