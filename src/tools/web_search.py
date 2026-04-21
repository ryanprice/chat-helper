import os

import httpx

MAX_RESULTS_LIMIT = 10


async def web_search(query: str, max_results: int = 5) -> str:
    """Search the web using a local SearXNG instance and return formatted results."""
    base_url = os.environ["SEARXNG_URL"].rstrip("/")
    count = min(max(1, max_results), MAX_RESULTS_LIMIT)

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            f"{base_url}/search",
            params={"q": query, "format": "json"},
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        data = response.json()

    results = data.get("results", [])[:count]
    if not results:
        return "No results found."

    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        url = r.get("url", "")
        description = r.get("content", "")
        lines.append(f"{i}. {title}\n   {url}\n   {description}")

    return "\n\n".join(lines)
