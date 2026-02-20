# chat-helper

A self-hosted Signal bot that runs as a linked device on your account and brings agentic AI tools into your chats. Send a slash command — with a replied-to message, an inline URL, or plain text — and the bot researches, expands, or condenses the content using a local LLM.

<img width="581" height="442" alt="image" src="https://github.com/user-attachments/assets/3c28cbab-ec74-4834-a7a4-79542164dec5" />

---

## Features

- **`/e [1–10]`** — Expand and research content. Level 1 is a single sentence; level 10 is an exhaustive deep-dive. Default: 5.
- **`/c [1–10]`** — Condense content. Level 1 is a light trim; level 10 is one to five words. Default: 5.
- **`/h`** — Print help text in the chat.
- **Flexible input** — commands work as a reply to a quoted message, or with a URL/text included inline:
  ```
  /e 3
  /c https://example.com/article
  https://www.youtube.com/watch?v=... /e 7
  /c 6 https://example.com
  ```
- **Smart content routing** — YouTube URLs → transcript fetch; other URLs → page fetch; no URL → web search.
- **Instant acknowledgment** — a `〔🤖🤔...〕` message is sent immediately so chat participants know the command was received.
- **Reply routing** — the bot owner gets responses in-channel; all other allowed users get a DM.
- **Allowlist** — optionally restrict the bot to a specific list of phone numbers.

---

## How it works

chat-helper runs as a [linked device](https://support.signal.org/hc/en-us/articles/360007320551) on your Signal account, similar to Signal Desktop. It connects to [signal-cli-rest-api](https://github.com/bbernhard/signal-cli-rest-api) via WebSocket to receive messages, and uses a local [Ollama](https://ollama.com) instance as its LLM backend.

```
Signal WebSocket
      │
      ▼
 parse_envelope()
      │
      ▼
 _parse_command()   ← finds command anywhere in message, extracts level + inline text
      │
      ├─ /h ──────────────────────────────────────────► send help to chat
      │
      ├─ /e or /c
      │       │
      │       ▼
      │   resolve content
      │   (quote text → inline text/URL → error)
      │       │
      │       ▼
      │   🤖🤔 acknowledgment sent immediately
      │       │
      │       ▼
      │   tool loop (LLM + tools, up to MAX_TOOL_ITERATIONS)
      │       ├─ YouTube URL   → get_transcript
      │       ├─ other URL     → fetch_page
      │       └─ no URL        → web_search
      │       │
      │       ▼
      │   _wrap() → framed response
      │       │
      └───────▼
          owner? → reply in-channel
          other? → DM
```

---

## Requirements

- Docker + Docker Compose
- [Ollama](https://ollama.com) running locally
- A [Brave Search API key](https://brave.com/search/api/) (free tier: 1 req/sec)
- A Signal account to link the bot to

---

## Setup

### 1. Clone the repo

```bash
git clone <repo-url>
cd chat-helper
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
SIGNAL_PHONE_NUMBER=+1234567890      # E.164 format — your Signal account number
BRAVE_API_KEY=your_key_here
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=glm-4.7-flash
ALLOWED_NUMBERS=                     # comma-separated E.164, or leave empty for all
TOOL_USE_FALLBACK=true               # set true if your model doesn't emit native tool_calls
MAX_TOOL_ITERATIONS=5
```

### 3. Pull the model

```bash
ollama pull glm-4.7-flash
```

Any Ollama model that supports tool use will work. `TOOL_USE_FALLBACK=true` enables a regex fallback for models that output tool calls as text rather than structured JSON.

### 4. Start signal-cli-rest-api and link your account

```bash
docker compose up signal-cli-rest-api
```

Open `http://localhost:8080/v1/qrcodelink?device_name=chat-helper` in a browser and scan the QR code with your Signal app (just like adding Signal Desktop).

### 5. Start the full stack

```bash
docker compose up
```

---

## Running locally (without Docker)

You'll still need signal-cli-rest-api running in Docker for the Signal WebSocket.

```bash
pip install -r requirements.txt
python -m src.main
```

> **Linux + Ollama note:** Ollama binds to `127.0.0.1` by default, so the Docker container can't reach it. Fix:
> ```bash
> sudo systemctl edit ollama
> # add under [Service]:
> # Environment="OLLAMA_HOST=0.0.0.0"
> sudo systemctl restart ollama
> ```

---

## Usage examples

| Message | What happens |
|---|---|
| Reply to a message + `/e` | Expands the quoted message at level 5 |
| Reply to a message + `/c 8` | Condenses the quoted message to near-minimum |
| `/e https://example.com/article` | Fetches the page and expands it |
| `/c 6 https://example.com/article` | Fetches the page and condenses at level 6 |
| `https://www.youtube.com/watch?v=xxx /e` | Fetches the YouTube transcript and expands it |
| `/e some topic I want to know about` | Web-searches the topic and expands the results |
| `/h` | Prints help in the current chat |

Responses are visually framed so they stand out in Signal:

```
〔🤖 chat-helper〕━━━━━━━━━━━━━━━━
...response text...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## Project structure

```
src/
├── main.py            # entry point — WebSocket listener
├── agent.py           # command parsing, tool loop, reply routing
├── signal_client.py   # Signal API send/receive wrappers
├── ollama_client.py   # Ollama chat API wrapper
├── models.py          # InboundMessage, Quote, GroupInfo dataclasses
├── config.py          # Settings loaded from .env
├── conversation.py    # placeholder (stateless — no history stored)
└── tools/
    ├── registry.py    # TOOL_REGISTRY + TOOL_DEFINITIONS for the LLM
    ├── web_search.py  # Brave Search API
    ├── transcript.py  # YouTube transcript fetcher
    └── fetch_page.py  # Generic web page content fetcher
```

---

## Adding a new command

1. Add the command string to `COMMANDS` in `src/agent.py`.
2. Add a handler method (`_run_yourcommand`) following the pattern of `_run_expand` / `_run_condense`.
3. Wrap the reply with `_wrap()` before sending.

## Adding a new tool

1. Create an `async def your_tool(...)` function in `src/tools/your_tool.py`.
2. Register it in `TOOL_REGISTRY` in `src/tools/registry.py`.
3. Add its JSON schema to `TOOL_DEFINITIONS` with a clear description telling the LLM when to use it.

---

## Security

- Logs never contain message content — only metadata (envelope fields, phone numbers, message lengths).
- Brave Search `max_results` is hard-capped at 10 regardless of what the LLM requests.
- Unauthorized numbers are silently dropped — no response is sent, to avoid confirming the bot exists.
- `fetch_page` sends a generic `User-Agent` and forwards no cookies or credentials.
- Inline content is wrapped in `<quote>` tags with a system prompt instruction to treat it as data only, not instructions (prompt injection hardening).

---

## Dependencies

| Package | Purpose |
|---|---|
| `httpx` | HTTP client (Brave Search, page fetch) |
| `websockets` | Signal WebSocket listener |
| `python-dotenv` | `.env` loading |
| `youtube-transcript-api` | YouTube caption fetching |
| `beautifulsoup4` | HTML stripping for `fetch_page` |

---

## License

MIT
