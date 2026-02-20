from src.tools.web_search import web_search
from src.tools.transcript import get_transcript
from src.tools.fetch_page import fetch_page

TOOL_REGISTRY = {
    "web_search": web_search,
    "get_transcript": get_transcript,
    "fetch_page": fetch_page,
}

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web for current information on a topic. "
                "Use this when no URL is provided and you need to research a topic."
            ),
            "parameters": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "description": "The search query"},
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return",
                        "default": 5,
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_transcript",
            "description": (
                "Fetch the spoken transcript of a YouTube video. "
                "Use this ONLY for YouTube URLs (youtube.com or youtu.be). "
                "Do NOT use for any other URLs — use fetch_page instead."
            ),
            "parameters": {
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The full YouTube video URL",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_page",
            "description": (
                "Fetch and extract the readable text content of any web page. "
                "Use this whenever a non-YouTube URL is provided. "
                "Do NOT use for YouTube URLs — use get_transcript instead."
            ),
            "parameters": {
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The full URL of the page to fetch",
                    },
                },
            },
        },
    },
]
