import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    signal_phone_number: str
    signal_api_url: str
    signal_api_token: str
    ollama_base_url: str
    ollama_model: str
    max_tool_iterations: int
    tool_use_fallback: bool
    allowed_numbers: frozenset[str]  # empty = allow all

    @classmethod
    def from_env(cls) -> "Settings":
        raw_allowed = os.getenv("ALLOWED_NUMBERS", "")
        allowed = frozenset(
            n.strip() for n in raw_allowed.split(",") if n.strip()
        )
        return cls(
            signal_phone_number=os.environ["SIGNAL_PHONE_NUMBER"],
            signal_api_url=os.getenv("SIGNAL_API_URL", "http://localhost:8080"),
            signal_api_token=os.getenv("SIGNAL_API_TOKEN", ""),
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            ollama_model=os.getenv("OLLAMA_MODEL", "glm-4.7-flash"),
            max_tool_iterations=int(os.getenv("MAX_TOOL_ITERATIONS", "5")),
            tool_use_fallback=os.getenv("TOOL_USE_FALLBACK", "false").lower() == "true",
            allowed_numbers=allowed,
        )
