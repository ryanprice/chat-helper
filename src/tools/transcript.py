import asyncio
import logging
from urllib.parse import parse_qs, urlparse

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import NoTranscriptFound, TranscriptsDisabled

logger = logging.getLogger(__name__)

# Truncate transcripts to keep within LLM context limits
MAX_TRANSCRIPT_CHARS = 15_000


def _extract_video_id(url: str) -> str | None:
    """Extract a YouTube video ID from any common URL format."""
    parsed = urlparse(url.strip())
    host = parsed.hostname or ""

    if "youtu.be" in host:
        return parsed.path.lstrip("/").split("?")[0] or None

    if "youtube.com" in host:
        if parsed.path == "/watch":
            return parse_qs(parsed.query).get("v", [None])[0]
        if parsed.path.startswith("/embed/"):
            return parsed.path.split("/embed/")[1].split("?")[0] or None
        if parsed.path.startswith("/shorts/"):
            return parsed.path.split("/shorts/")[1].split("?")[0] or None

    return None


def _fetch(video_id: str) -> str:
    fetched = YouTubeTranscriptApi().fetch(video_id)
    text = " ".join(snippet.text for snippet in fetched)

    if len(text) > MAX_TRANSCRIPT_CHARS:
        text = (
            text[:MAX_TRANSCRIPT_CHARS]
            + f"\n\n[Transcript truncated at {MAX_TRANSCRIPT_CHARS:,} characters]"
        )
    return text


async def get_transcript(url: str) -> str:
    """Fetch the spoken transcript of a YouTube video and return it as plain text."""
    video_id = _extract_video_id(url)
    if not video_id:
        return f"Could not extract a video ID from: {url}"

    logger.info("Fetching transcript for video ID %s", video_id)
    try:
        text = await asyncio.to_thread(_fetch, video_id)
        logger.info("Transcript fetched: %d chars", len(text))
        return f"[YouTube transcript — {url}]\n\n{text}"
    except TranscriptsDisabled:
        return "Transcripts are disabled for this video."
    except NoTranscriptFound:
        return "No transcript is available for this video (try a video with captions enabled)."
    except Exception as e:
        logger.error("Transcript fetch failed for %s: %s", video_id, e)
        return f"Error fetching transcript: {e}"
