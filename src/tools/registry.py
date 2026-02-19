from src.tools.web_search import web_search
from src.tools.transcript import get_transcript

TOOL_REGISTRY = {
    "web_search": web_search,
    "get_transcript": get_transcript,
}

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for current information on a topic.",
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
                "Use this whenever the user's quoted message contains a YouTube URL "
                "(youtube.com or youtu.be). Returns the full transcript as plain text."
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
]
