# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Signal chat bot that listens for slash commands sent as replies to messages:
- `/e [1-10]` — expand/research the quoted message (1 = one sentence, 10 = exhaustive deep-dive, default 5)
- `/c [1-10]` — condense the quoted message (1 = light trim, 10 = one to five words, default 5) It uses Ollama (GLM-4.7-flash) with an agentic tool loop (Brave Search API) and always responds via DM to the requester, never in the group chat.

The bot runs as a **linked device** on the owner's Signal account (like Signal Desktop), so it receives all messages on the account. It silently ignores everything that isn't a slash command reply.

## Running locally (outside Docker)

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in SIGNAL_PHONE_NUMBER and BRAVE_API_KEY at minimum
python -m src.main
```

The Signal API must already be running (`docker compose up signal-cli-rest-api`) and Ollama must be available at `OLLAMA_BASE_URL`.

On Linux, Ollama binds to `127.0.0.1` by default — Docker containers can't reach it. Set `OLLAMA_HOST=0.0.0.0` via `sudo systemctl edit ollama` and restart.

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
                                              /e → tool loop → Ollama → DM
                                              /c → tool loop → Ollama → DM
```

**syncMessage handling:** when the bot owner sends a command from their own phone, signal-cli receives a `syncMessage` (copy of sent message) rather than a `dataMessage`. `parse_envelope()` extracts `syncMessage.sentMessage` to handle this case.

**Key design decisions:**
- Each command invocation is **stateless** — no conversation history is stored. `src/conversation.py` is an intentional placeholder.
- Responses always go to `source_number` as a DM, even when the command originated in a group chat.
- The agentic loop (`src/agent.py:_tool_loop`) caps at `MAX_TOOL_ITERATIONS` then forces a final Ollama call without tools.
- `TOOL_USE_FALLBACK=true` activates regex parsing of `<tool_call>{...}</tool_call>` tags from model text output — needed if GLM doesn't emit native `tool_calls`.
- Quote text is wrapped in `<quote>` tags and the system prompt instructs the model to treat it as data, not instructions (prompt injection hardening).
- Commands are intentionally short (`/e`, `/c`) for easy mobile use. The level argument (1–10) is parsed by `_parse_level()` in `agent.py` and clamped — invalid values silently fall back to 5. Level guidance strings live in `_EXPAND_LEVEL_GUIDANCE` and `_CONDENSE_LEVEL_GUIDANCE` dicts.

**Adding a new command:** add its string to `COMMANDS` in `src/agent.py` and add a handler method following the `_run_expand` / `_run_condense` pattern. Keep commands short (e.g. `/e`, `/c`) to minimise typing in mobile Signal.

**Adding a new tool:** create the async function in `src/tools/`, register it in `TOOL_REGISTRY` and add its schema to `TOOL_DEFINITIONS` in `src/tools/registry.py`.

## Configuration

All config comes from `.env` (see `.env.example`). Key vars:
- `SIGNAL_PHONE_NUMBER` — E.164 format, required
- `BRAVE_API_KEY` — required for `/expand` web search
- `ALLOWED_NUMBERS` — comma-separated E.164 numbers permitted to use the bot; leave empty to allow all
- `TOOL_USE_FALLBACK` — set `true` if the model doesn't emit native `tool_calls`
- `MAX_TOOL_ITERATIONS` — max agentic loop iterations before forcing a final answer

## Security notes

- Logs never contain message content — only metadata (envelope key names, phone numbers, message lengths)
- `max_results` for Brave Search is hard-capped at 10 in `src/tools/web_search.py` regardless of what the LLM requests
- Unauthorized numbers are silently dropped (no response sent, to avoid confirming the bot exists)
