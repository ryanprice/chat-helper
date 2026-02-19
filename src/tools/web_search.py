import os

import httpx

BRAVE_API_URL = "https://api.search.brave.com/res/v1/web/search"


MAX_RESULTS_LIMIT = 10


async def web_search(query: str, max_results: int = 5) -> str:
    """Search the web using the Brave Search API and return formatted results."""
    api_key = os.environ["BRAVE_API_KEY"]
    count = min(max(1, max_results), MAX_RESULTS_LIMIT)

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            BRAVE_API_URL,
            params={"q": query, "count": count},
            headers={
                "X-Subscription-Token": api_key,
                "Accept": "application/json",
            },
        )
        response.raise_for_status()
        data = response.json()

    results = data.get("web", {}).get("results", [])
    if not results:
        return "No results found."

    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        url = r.get("url", "")
        description = r.get("description", "")
        lines.append(f"{i}. {title}\n   {url}\n   {description}")

    return "\n\n".join(lines)
