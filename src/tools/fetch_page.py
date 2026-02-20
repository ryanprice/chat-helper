import logging

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

MAX_PAGE_CHARS = 15_000

_SKIP_TAGS = {"script", "style", "nav", "header", "footer", "aside", "noscript"}


def _extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(list(_SKIP_TAGS)):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    lines = [line for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


async def fetch_page(url: str) -> str:
    """Fetch the readable text content of a web page and return it as plain text."""
    logger.info("Fetching page: %s", url)
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; chat-helper/1.0)"},
            )
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "html" not in content_type and "text" not in content_type:
                return f"Unsupported content type: {content_type}"
            text = _extract_text(response.text)
    except httpx.HTTPStatusError as e:
        return f"HTTP error {e.response.status_code} fetching {url}"
    except Exception as e:
        logger.error("fetch_page failed for %s: %s", url, e)
        return f"Error fetching page: {e}"

    if len(text) > MAX_PAGE_CHARS:
        text = text[:MAX_PAGE_CHARS] + f"\n\n[Page truncated at {MAX_PAGE_CHARS:,} characters]"

    logger.info("fetch_page: %d chars from %s", len(text), url)
    return f"[Page content — {url}]\n\n{text}"
