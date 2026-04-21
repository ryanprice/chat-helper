# chat-helper

A self-hosted Signal bot that runs as a linked device on your account and brings agentic AI tools into your chats. Send a slash command — with a replied-to message, an inline URL, or plain text — and the bot condenses the content using a local LLM. An optional **watcher agent** passively observes conversations and proactively surfaces research, summaries, or classifications when it decides something is worth your attention.
<p align="center">
  <img width="581" height="442" alt="image" src="https://github.com/user-attachments/assets/3c28cbab-ec74-4834-a7a4-79542164dec5" />
</p>
---

## Features

- **`/c [1–10]`** — Condense content. Level 1 is a light trim; level 10 is one to five words. Default: 5.
- **`/h`** — Print help text in the chat.
- **`/fb 0`** / **`/fb 1`** *(owner only)* — Rate the most recent watcher action as not-useful or useful. Feedback is persisted and fed back into future decision-gate prompts.
- **`kkk`** or **`/kkk`** *(owner only)* — Kill switch. Cancels every in-flight task (tool loops, pending replies) and DMs you a confirmation.
- **Watcher agent** *(opt-in via `WATCHER_ENABLED=true`)* — passively observes non-command chat, decides autonomously when a research/summarize/classify/execute action is warranted, and DMs the owner with the result and a feedback prompt. Cooldown-limited per chat.
- **Flexible input** — commands work as a reply to a quoted message, or with a URL/text included inline:
  ```
  /c 3
  /c https://example.com/article
  https://www.youtube.com/watch?v=... /c 7
  /c 6 https://example.com
  ```
- **Smart content routing** — YouTube URLs → transcript fetch; Twitter/X URLs → fxtwitter API; other URLs → page fetch.
- **Instant acknowledgment** — a `〔🤖🤔...〕` message is sent immediately so chat participants know the command was received.
- **Reply routing** — the bot owner gets responses in-channel; all other allowed users get a DM. Watcher reports always DM the owner.
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
      ├─ kill switch ("kkk" from owner) → cancel every active task
      │
      ▼ each inbound message fans out to BOTH:
 ┌──────────────────────────────┬────────────────────────────────────┐
 ▼                              ▼
 Command Agent                  Watcher Agent (if WATCHER_ENABLED)
 _parse_command()               /fb rating? → FeedbackLog, done
      │                         should_observe? (skip short/slash/self)
      ├─ /h → help              buffer to per-chat deque
      ├─ /c                     every N msgs, not in cooldown:
      │   resolve content          decision gate LLM → {act, type, reason}
      │   🤖🤔 ack                 act? → tool loop → DM owner w/ action ID
      │   tool loop:
      │    ├─ YouTube → get_transcript
      │    ├─ X/Twitter → fetch_page (fxtwitter)
      │    ├─ other URL → fetch_page
      │    └─ no URL → web_search (SearXNG)
      │   _wrap() → reply
      └─ owner? in-channel • else DM
```

---

## Requirements

- Docker + Docker Compose
- [Ollama](https://ollama.com) running locally
- A local [SearXNG](https://github.com/searxng/searxng) instance with JSON format enabled
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
SEARXNG_URL=http://host.docker.internal:8888
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=glm-4.7-flash
ALLOWED_NUMBERS=                     # comma-separated E.164, or leave empty for all
TOOL_USE_FALLBACK=true               # set true if your model doesn't emit native tool_calls
MAX_TOOL_ITERATIONS=5

# Watcher agent (passive chat monitor) — opt-in
WATCHER_ENABLED=false
WATCHER_CONTEXT_WINDOW=20            # messages to keep per chat in memory
WATCHER_BATCH_SIZE=5                 # messages to accumulate before firing decision gate
WATCHER_COOLDOWN_SECONDS=300         # min seconds between watcher actions per chat
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
| Reply to a message + `/c` | Condenses the quoted message at level 5 |
| Reply to a message + `/c 8` | Condenses the quoted message to near-minimum |
| `/c https://example.com/article` | Fetches the page and condenses it |
| `/c 6 https://example.com/article` | Fetches the page and condenses at level 6 |
| `https://www.youtube.com/watch?v=xxx /c` | Fetches the YouTube transcript and condenses it |
| `/h` | Prints help in the current chat |
| `/fb 1` *(owner, after a watcher report)* | Marks the last watcher action as useful |
| `/fb 0` *(owner, after a watcher report)* | Marks the last watcher action as not useful |
| `kkk` *(owner)* | Kill switch — cancels every in-flight task |

### Watcher example

With `WATCHER_ENABLED=true`, the watcher observes every 5th non-command message in a chat and decides whether to act. For example:

```
[alice]: did you see the trailer?
[bob]:   which one
[alice]: the dune part 3
[bob]:   oh nice
[alice]: wait when does dune part 3 actually come out?
```

The decision gate returns `{"act": true, "action_type": "research", "reason": "release-date question"}`, runs the tool loop (→ `web_search` via SearXNG), and DMs you:

```
〔🤖 chat-helper〕━━━━━━━━━━━━━━━━
👁 Watcher (research): release-date question

Dune: Part Three is scheduled for December 18, 2026…

[ID: w-a3f9c1] · /fb 1 useful · /fb 0 not
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

You then rate it with `/fb 1` or `/fb 0` — the rating is persisted to `data/watcher_feedback.jsonl` and summarized into the next decision-gate prompt, so the watcher learns your taste over time.

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
├── main.py            # entry point — WebSocket listener + task tracking + kill switch
├── base_agent.py      # shared tool loop + _wrap() response framing
├── agent.py           # slash-command agent (/c, /h) — command parsing, reply routing
├── watcher.py         # passive watcher agent — decision gate, action dispatch
├── feedback.py        # JSONL-backed feedback log + summary for gate prompts
├── signal_client.py   # Signal API send/receive wrappers
├── ollama_client.py   # Ollama chat API wrapper
├── models.py          # InboundMessage, Quote, GroupInfo dataclasses
├── config.py          # Settings loaded from .env
├── conversation.py    # placeholder (stateless — no history stored)
└── tools/
    ├── registry.py    # TOOL_REGISTRY + TOOL_DEFINITIONS for the LLM
    ├── web_search.py  # SearXNG JSON API
    ├── transcript.py  # YouTube transcript fetcher
    └── fetch_page.py  # Generic web page content fetcher (+ fxtwitter for X URLs)

data/
└── watcher_feedback.jsonl   # append-only feedback log (auto-created)
```

---

## Adding a new command

1. Add the command string to `COMMANDS` in `src/agent.py`.
2. Add a handler method (`_run_yourcommand`) following the pattern of `_run_condense`.
3. Wrap the reply with `_wrap()` before sending.

> `/fb` is **not** in `COMMANDS` — it's intercepted inside `WatcherAgent._check_feedback` so it only applies when the watcher is enabled.

## Adding a new tool

1. Create an `async def your_tool(...)` function in `src/tools/your_tool.py`.
2. Register it in `TOOL_REGISTRY` in `src/tools/registry.py`.
3. Add its JSON schema to `TOOL_DEFINITIONS` with a clear description telling the LLM when to use it.

---

## Security

- Logs never contain message content — only metadata (envelope fields, phone numbers, message lengths).
- `web_search` `max_results` is hard-capped at 10 regardless of what the LLM requests.
- Unauthorized numbers are silently dropped — no response is sent, to avoid confirming the bot exists.
- `fetch_page` sends a generic `User-Agent` and forwards no cookies or credentials. Twitter/X URLs are resolved via the [fxtwitter](https://github.com/FixTweet/FxTwitter) JSON API rather than direct scraping.
- Inline content is wrapped in `<quote>` tags with a system prompt instruction to treat it as data only, not instructions (prompt injection hardening).

---

## Dependencies

| Package | Purpose |
|---|---|
| `httpx` | HTTP client (SearXNG, page fetch) |
| `websockets` | Signal WebSocket listener |
| `python-dotenv` | `.env` loading |
| `youtube-transcript-api` | YouTube caption fetching |
| `beautifulsoup4` | HTML stripping for `fetch_page` |

---

## License

MIT
