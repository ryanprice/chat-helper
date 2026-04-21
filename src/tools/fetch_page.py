import json
import logging
from urllib.parse import urlparse, urlunparse

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


_TWITTER_HOSTS = {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}


def _is_twitter_url(url: str) -> bool:
    return urlparse(url).hostname in _TWITTER_HOSTS


def _rewrite_twitter_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname in _TWITTER_HOSTS:
        return urlunparse(parsed._replace(netloc="fxtwitter.com"))
    return url


async def _fetch_tweet(url: str, client: httpx.AsyncClient) -> str:
    """Use the fxtwitter JSON API to extract tweet text reliably."""
    parsed = urlparse(url)
    api_url = urlunparse(parsed._replace(netloc="api.fxtwitter.com"))
    logger.info("Fetching tweet via fxtwitter API: %s", api_url)
    response = await client.get(
        api_url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; chat-helper/1.0)"},
    )
    response.raise_for_status()
    data = response.json()
    tweet = data.get("tweet", {})
    author = tweet.get("author", {})
    name = author.get("name", "")
    screen_name = author.get("screen_name", "")
    text = tweet.get("text", "")
    created_at = tweet.get("created_at", "")
    parts = []
    if name or screen_name:
        parts.append(f"{name} (@{screen_name})")
    if created_at:
        parts.append(created_at)
    parts.append(text)
    # include quoted tweet if present
    quoted = tweet.get("quote", {})
    if quoted:
        q_author = quoted.get("author", {})
        q_text = quoted.get("text", "")
        q_name = q_author.get("screen_name", "")
        if q_text:
            parts.append(f"[Quoting @{q_name}: {q_text}]")
    return "\n".join(parts)


async def fetch_page(url: str) -> str:
    """Fetch the readable text content of a web page and return it as plain text."""
    logger.info("Fetching page: %s", url)
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            if _is_twitter_url(url):
                text = await _fetch_tweet(url, client)
                logger.info("fetch_page (tweet): %d chars from %s", len(text), url)
                return f"[Tweet — {url}]\n\n{text}"

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
