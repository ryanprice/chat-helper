from dataclasses import dataclass
from typing import Optional


@dataclass
class Quote:
    author_number: str   # E.164 number of the original message author
    text: str            # text of the message being replied to
    timestamp: int       # original message timestamp (ms)


@dataclass
class GroupInfo:
    group_id: str
    group_type: str


@dataclass
class InboundMessage:
    source_number: str
    source_name: str
    message_text: str
    timestamp: int
    group_info: Optional[GroupInfo]
    quote: Optional[Quote]
