# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Signal chat bot that listens for slash commands. Commands can appear anywhere in the message — as a reply to another message (quoting it), or with inline text/URL in the same message:
- `/e [1-10]` — expand/research content (1 = one sentence, 10 = exhaustive deep-dive, default 5)
- `/c [1-10]` — condense content (1 = light trim, 10 = one to five words, default 5)
- `/h` — post help text directly in the chat (no content needed)

**Content resolution:** quote text (replied-to message) takes priority; if absent, any inline text or URL in the same message is used. If neither is present, the bot sends an error.

**URL handling:** YouTube URLs → `get_transcript`; any other URL → `fetch_page`; no URL → `web_search`.

**Reply routing:** the bot owner (`SIGNAL_PHONE_NUMBER`) gets responses in the same chat/channel where they sent the command. All other users get a DM.

All agent responses are framed with a `〔🤖 chat-helper〕━━━` header and `━━━` footer (see `_wrap()` in `src/agent.py`) so they're visually distinct in Signal.

The bot runs as a **linked device** on the owner's Signal account (like Signal Desktop), so it receives all messages on the account and silently ignores everything that isn't a slash command.

## Running locally (outside Docker)

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in SIGNAL_PHONE_NUMBER and BRAVE_API_KEY at minimum
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

## Architecture

**Message flow:**
```
Signal WebSocket → parse_envelope() → InboundMessage → Agent.handle_message()
                                                              ↓
                                             allowlist check (ALLOWED_NUMBERS)
                                                              ↓
                                         _parse_command() → cmd, level, inline_text
                                                              ↓
                                    /h → send_to_chat (always in-channel)
                                    /e → tool loop → Ollama → _wrap() → _reply()
                                    /c → tool loop → Ollama → _wrap() → _reply()
                                                                              ↓
                                                         owner? → send_to_chat
                                                         others? → send_message (DM)
```

**syncMessage handling:** when the bot owner sends a command from their own phone, signal-cli receives a `syncMessage` (copy of sent message) rather than a `dataMessage`. `parse_envelope()` extracts `syncMessage.sentMessage` to handle this. Reply routing uses:
- `sentMessage.groupInfo.groupId` → send to group
- `sentMessage.destinationNumber` → send to 1:1 DM partner (phone-number contacts)
- `sentMessage.destinationUuid` → send to 1:1 DM partner (username-only contacts; `destinationNumber` is null for these)
- fallback → `source_number`

**Key design decisions:**
- Each command invocation is **stateless** — no conversation history is stored. `src/conversation.py` is an intentional placeholder.
- The agentic loop (`src/agent.py:_tool_loop`) caps at `MAX_TOOL_ITERATIONS` then forces a final Ollama call without tools.
- A 1.1s `asyncio.sleep` after each tool call respects the Brave Search free-tier rate limit (1 req/sec).
- `TOOL_USE_FALLBACK=true` activates regex parsing of `<tool_call>{...}</tool_call>` tags from model text — needed if GLM doesn't emit native `tool_calls`.
- Content (quote or inline text) is wrapped in `<quote>` tags and system prompts instruct the model to treat it as data, not instructions (prompt injection hardening).
- Command parsing is handled by `_parse_command()` in `agent.py`: scans all tokens for the command (which may appear anywhere in the message), consumes the immediately-following token as the level digit if valid (1–10, clamped), collects remaining tokens as `inline_text`. Invalid or absent level falls back to 5. Guidance strings live in `_EXPAND_LEVEL_GUIDANCE` / `_CONDENSE_LEVEL_GUIDANCE` dicts.
- An immediate `〔🤖🤔...〕` acknowledgment is sent via `_reply()` as soon as a valid command and content are confirmed, before the tool loop runs.

**Adding a new command:** add its string to `COMMANDS` in `src/agent.py`, add a handler following `_run_expand` / `_run_condense`, and wrap the reply with `_wrap()` before sending.

**Available tools** (called automatically by the LLM during the tool loop):
- `web_search` — Brave Search API, capped at 10 results, 1.1s delay between calls (free-tier rate limit). Used when no URL is present.
- `get_transcript` — fetches YouTube transcript via `youtube-transcript-api` (v1.0+); uses `YouTubeTranscriptApi().fetch(video_id)` instance API; truncated at 15,000 chars. Supports `youtube.com/watch`, `youtu.be`, `/embed/`, and `/shorts/` URL formats. Works on any public video with captions; fails gracefully on private/age-restricted/caption-disabled videos.
- `fetch_page` — fetches arbitrary web page content via `httpx`, strips boilerplate (scripts, nav, footer, etc.) with `beautifulsoup4`, and returns readable text truncated at 15,000 chars. Used for any non-YouTube URL.

**Tool selection is guided by tool descriptions** in `TOOL_DEFINITIONS` (`src/tools/registry.py`) — the LLM reads these and picks the appropriate tool automatically.

**Adding a new tool:** create the async function in `src/tools/`, register it in `TOOL_REGISTRY` and add its schema to `TOOL_DEFINITIONS` in `src/tools/registry.py`.

## Configuration

All config comes from `.env` (see `.env.example`). Key vars:
- `SIGNAL_PHONE_NUMBER` — E.164 format, required; also identifies the owner for in-channel reply routing
- `BRAVE_API_KEY` — required for `/e` web search
- `ALLOWED_NUMBERS` — comma-separated E.164 numbers permitted to use the bot; leave empty to allow all
- `TOOL_USE_FALLBACK` — set `true` if the model doesn't emit native `tool_calls`
- `MAX_TOOL_ITERATIONS` — max agentic loop iterations before forcing a final answer

## Security notes

- Logs never contain message content — only metadata (envelope key names, phone numbers, message lengths)
- `max_results` for Brave Search is hard-capped at 10 in `src/tools/web_search.py` regardless of what the LLM requests
- Unauthorized numbers are silently dropped (no response sent, to avoid confirming the bot exists)
- `fetch_page` sends a generic `User-Agent` header; no cookies or credentials are forwarded
