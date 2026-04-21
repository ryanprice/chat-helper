# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Signal chat bot with two independent agents sharing one Ollama-backed tool loop:

1. **Command agent** (`src/agent.py`) — responds to slash commands from any allowed user.
2. **Watcher agent** (`src/watcher.py`, opt-in via `WATCHER_ENABLED=true`) — passively observes every non-command message, decides autonomously when to act, and DMs the owner with results.

### Slash commands
Commands can appear anywhere in the message — as a reply to another message (quoting it), or with inline text/URL in the same message:
- `/c [1-10]` — condense content (1 = light trim, 10 = one to five words, default 5)
- `/h` — post help text directly in the chat (no content needed)
- `/fb 0` / `/fb 1` — owner-only; rate the most recent unrated watcher action as not-useful / useful. Feeds into future decision-gate prompts.
- `kkk` or `/kkk` — owner-only **kill switch**; cancels every active asyncio task (ongoing tool loops, in-flight replies) and sends a confirmation DM. Handled in `src/main.py:_handle_kill` before the agent/watcher dispatch.

**Content resolution:** quote text (replied-to message) takes priority; if absent, any inline text or URL in the same message is used. If neither is present, the bot sends an error.

**URL handling:** YouTube URLs → `get_transcript`; Twitter/X URLs → `fetch_page` (fxtwitter API); any other URL → `fetch_page`. If no URL and no quoted text, the bot returns an error.

**Reply routing:** the bot owner (`SIGNAL_PHONE_NUMBER`) gets responses in the same chat/channel where they sent the command. All other users get a DM. Watcher reports always go to the owner via DM.

All agent responses are framed with a `〔🤖 chat-helper〕━━━` header and `━━━` footer (see `_wrap()` in `src/base_agent.py`) so they're visually distinct in Signal.

The bot runs as a **linked device** on the owner's Signal account (like Signal Desktop), so it receives all messages on the account and silently ignores everything that isn't a slash command or watcher-worthy context.

## Running locally (outside Docker)

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in SIGNAL_PHONE_NUMBER and SEARXNG_URL at minimum
python -m src.main
```

The Signal API must already be running (`docker compose up signal-cli-rest-api`) and Ollama must be available at `OLLAMA_BASE_URL`.

On Linux, Ollama binds to `127.0.0.1` by default — Docker containers can't reach it. Fix: `sudo systemctl edit ollama`, add `[Service]\nEnvironment="OLLAMA_HOST=0.0.0.0"`, then `sudo systemctl restart ollama`.

## Running with Docker

```bash
docker compose up signal-cli-rest-api          # step 1: start API only
# scan QR at http://localhost:8080/v1/qrcodelink?device_name=chat-helper
ollama pull glm-4.7-flash                      # step 2: pull model
docker compose up                              # step 3: full stack
```

`MODE=json-rpc` in docker-compose.yml is required — other modes don't expose the WebSocket receive endpoint.

**Dev vs prod builds:** `docker-compose.yml` bakes source code into the image at build time (`build: .`). A `--build` flag is required whenever Python files change. To avoid rebuilding on every code change during development, create a `docker-compose.override.yml` (auto-merged by Docker Compose) with a volume mount:

```yaml
services:
  chat-helper:
    volumes:
      - ./src:/app/src
    restart: "no"
```

For CI/prod, exclude the override explicitly: `docker compose -f docker-compose.yml up --build`.

## Architecture

**Message flow:**
```
Signal WebSocket → parse_envelope() → InboundMessage
                                          │
                   ┌──────── main.py ─────┴──────────────────┐
                   ▼                                         ▼
     kill switch (owner + "kkk"/"/kkk")?      every inbound msg fans out:
            cancel all tasks                       Agent.handle_message()
                                                   WatcherAgent.observe()  (if enabled)

Agent.handle_message()  ────── allowlist check (ALLOWED_NUMBERS)
                               _parse_command() → cmd, level, inline_text
                                                              ↓
                                    /h → send_to_chat (always in-channel)
                                    /c → tool loop → Ollama → _wrap() → _reply()
                                                                              ↓
                                                         owner? → send_to_chat
                                                         others? → send_message (DM)

WatcherAgent.observe() ──── /fb 0|1 (owner)?  record feedback, DM confirmation
                            should_observe?   (skip short msgs, slash cmds, self-sends)
                            buffer message to per-chat deque
                            every WATCHER_BATCH_SIZE msgs + not in cooldown:
                                decision gate  →  JSON {act, action_type, reason}
                                   act=true → tool loop → DM owner with action ID
                                              FeedbackLog.record(action_id, ...)
```

**syncMessage handling:** when the bot owner sends a command from their own phone, signal-cli receives a `syncMessage` (copy of sent message) rather than a `dataMessage`. `parse_envelope()` extracts `syncMessage.sentMessage` to handle this. Reply routing uses:
- `sentMessage.groupInfo.groupId` → send to group
- `sentMessage.destinationNumber` → send to 1:1 DM partner (phone-number contacts)
- `sentMessage.destinationUuid` → send to 1:1 DM partner (username-only contacts; `destinationNumber` is null for these)
- fallback → `source_number`

**Key design decisions:**
- Each command invocation is **stateless** — no conversation history is stored. `src/conversation.py` is an intentional placeholder.
- The agentic loop (`src/base_agent.py:_tool_loop`) caps at `MAX_TOOL_ITERATIONS` then forces a final Ollama call without tools.
- `TOOL_USE_FALLBACK=true` activates regex parsing of `<tool_call>{...}</tool_call>` tags from model text — needed if GLM doesn't emit native `tool_calls`.
- Content (quote or inline text) is wrapped in `<quote>` tags and system prompts instruct the model to treat it as data, not instructions (prompt injection hardening).
- Command parsing is handled by `_parse_command()` in `agent.py`: scans all tokens for the command (which may appear anywhere in the message), consumes the immediately-following token as the level digit if valid (1–10, clamped), collects remaining tokens as `inline_text`. Invalid or absent level falls back to 5. Guidance strings live in the `_CONDENSE_LEVEL_GUIDANCE` dict.
- An immediate `〔🤖🤔...〕` acknowledgment is sent via `_reply()` as soon as a valid command and content are confirmed, before the tool loop runs.
- Every inbound handler is wrapped in `_track()` (see `main.py`) which adds the task to a global set. The kill switch cancels that set wholesale — useful when a tool loop hangs or the model is producing runaway output.

**Watcher design:**
- **Decision gate** (`_decision_gate`): lightweight LLM call (no tools) that returns strict JSON `{"act": bool, "action_type": str, "reason": str}`. Markdown code-fence stripping is applied before `json.loads`.
- **Action types:** `research` (web search), `summarize` (thread summary), `classify` (urgency/routing), `execute` (multi-step tool use). Each maps to a distinct system prompt in `_ACTION_SYSTEMS`.
- **Batching:** only fires the decision gate once every `WATCHER_BATCH_SIZE` observed messages per chat — avoids one-shot gate calls on every message.
- **Cooldown:** `WATCHER_COOLDOWN_SECONDS` between actions per chat. Tracked per `chat_id` (`group:<id>` or `dm:<number>`).
- **Filtering:** `_should_observe` skips messages shorter than 8 chars, any message starting with `/`, and outbound self-sends (`source_number == signal_phone_number` with no `destination_number`).
- **Feedback loop:** every watcher action gets a short `w-<hex>` ID. Owner replies `/fb 1` or `/fb 0`. `FeedbackLog` (JSONL at `data/watcher_feedback.jsonl`) persists entries and summarizes the last 20 rated actions into the next decision-gate system prompt — closing the loop without needing fine-tuning.
- **No retrieval/RAG:** the watcher's context is purely the in-memory `deque` of the last `WATCHER_CONTEXT_WINDOW` messages per chat. There is no embedding store.

**Adding a new command:** add its string to `COMMANDS` in `src/agent.py`, add a handler following `_run_condense`, and wrap the reply with `_wrap()` before sending. Note that `/fb` is handled inside `WatcherAgent._check_feedback`, not in the command `COMMANDS` set.

**Available tools** (called automatically by the LLM during the tool loop):
- `web_search` — local SearXNG instance (`SEARXNG_URL`, JSON format), capped at 10 results. Available to the tool loop though rarely needed for condensing.
- `get_transcript` — fetches YouTube transcript via `youtube-transcript-api` (v1.0+); uses `YouTubeTranscriptApi().fetch(video_id)` instance API; truncated at 15,000 chars. Supports `youtube.com/watch`, `youtu.be`, `/embed/`, and `/shorts/` URL formats. Works on any public video with captions; fails gracefully on private/age-restricted/caption-disabled videos.
- `fetch_page` — fetches arbitrary web page content via `httpx`, strips boilerplate (scripts, nav, footer, etc.) with `beautifulsoup4`, and returns readable text truncated at 15,000 chars. Used for any non-YouTube URL. **Twitter/X URLs** (`x.com`, `twitter.com`) are handled specially: `fetch_page` calls the `api.fxtwitter.com` JSON API instead of scraping HTML, returning author, timestamp, tweet text, and any quoted tweet cleanly.

**Tool selection is guided by tool descriptions** in `TOOL_DEFINITIONS` (`src/tools/registry.py`) — the LLM reads these and picks the appropriate tool automatically.

**Adding a new tool:** create the async function in `src/tools/`, register it in `TOOL_REGISTRY` and add its schema to `TOOL_DEFINITIONS` in `src/tools/registry.py`.

## Configuration

All config comes from `.env` (see `.env.example`). Key vars:
- `SIGNAL_PHONE_NUMBER` — E.164 format, required; also identifies the owner for in-channel reply routing, `/fb` authorization, and kill switch
- `SEARXNG_URL` — base URL of a local SearXNG instance (must have JSON format enabled); required for `web_search` tool calls
- `OLLAMA_BASE_URL` / `OLLAMA_MODEL` — defaults: `http://localhost:11434` / `glm-4.7-flash`
- `ALLOWED_NUMBERS` — comma-separated E.164 numbers permitted to use the bot; leave empty to allow all
- `TOOL_USE_FALLBACK` — set `true` if the model doesn't emit native `tool_calls`
- `MAX_TOOL_ITERATIONS` — max agentic loop iterations before forcing a final answer
- `WATCHER_ENABLED` — default `false`; set `true` to activate the passive watcher agent
- `WATCHER_CONTEXT_WINDOW` — per-chat deque size of recent messages fed into the gate (default 20)
- `WATCHER_BATCH_SIZE` — number of observed messages between decision-gate invocations per chat (default 5)
- `WATCHER_COOLDOWN_SECONDS` — min seconds between watcher actions per chat (default 300)

## Security notes

- Logs never contain message content — only metadata (envelope key names, phone numbers, message lengths)
- `max_results` for `web_search` is hard-capped at 10 in `src/tools/web_search.py` regardless of what the LLM requests
- Unauthorized numbers are silently dropped (no response sent, to avoid confirming the bot exists)
- `fetch_page` sends a generic `User-Agent` header; no cookies or credentials are forwarded
