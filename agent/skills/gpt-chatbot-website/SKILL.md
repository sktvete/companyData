---
name: gpt-chatbot-website
description: >-
  Build a ChatGPT-subscription-powered website with OAuth login and custom
  tool calling. Uses OpenAI's OAuth PKCE flow so users sign in with their
  existing ChatGPT Plus/Pro account -- no API key needed. Chat goes through
  the Codex Responses API with server-side tool execution. Use when building
  an AI chatbot website, ChatGPT OAuth integration, subscription-based chat
  UI, or tool-calling chat app.
---

# GPT Chatbot Website

Build a web chat UI powered by a user's existing ChatGPT subscription via OAuth. No API key required -- users sign in with their OpenAI account and chat through their subscription quota.

## Architecture

```
Browser (HTML/CSS/JS)
  |
  | SSE stream
  v
Express server (Node 20+, ES modules)
  |
  |-- OAuth PKCE --> auth.openai.com
  |-- Responses API --> chatgpt.com/backend-api/codex/responses
  |-- Tool execution --> EODHD, DuckDuckGo, custom APIs
```

**Key components:**
- `server.js` -- Express server handling OAuth, chat proxy, and tool-calling loop
- `tools.js` -- Tool definitions (Responses API format) and execution handlers
- `public/` -- Static frontend: index.html, style.css, app.js
- `.env` -- API keys for tool backends (e.g. `EODHD_API_KEY`)
- `.session.json` -- Persisted OAuth tokens (gitignored)

## Quick Start

### Step 1: Scaffold

```json
{
  "type": "module",
  "dependencies": {
    "express": "^4.21.0",
    "dotenv": "^17.0.0",
    "duckduckgo-search": "^1.0.7"
  }
}
```

### Step 2: Server (`server.js`)

The server has four concerns:

1. **OAuth PKCE** -- Generate auth URL, run callback server on port 1455, exchange code for tokens, persist session. See [oauth-reference.md](oauth-reference.md).

2. **Chat proxy** -- Convert frontend messages to Responses API input format, stream response via SSE. See [responses-api.md](responses-api.md).

3. **Tool-calling loop** -- When GPT returns function calls: execute all tools in parallel with `Promise.all`, append both `function_call` and `function_call_output` items to input, send another request. Repeat up to 5 rounds. See [responses-api.md](responses-api.md).

4. **Static file serving** -- `express.static("public")`.

### Step 3: Tools (`tools.js`)

Export `toolDefinitions` (array of Responses API tool objects) and `executeTool(name, args)` (async dispatcher). See [tool-patterns.md](tool-patterns.md).

### Step 4: Frontend (`public/`)

- **Connect screen** -- "Sign in with ChatGPT" button. Calls `/api/auth/login`, opens auth URL in popup, polls `/api/auth/status` until authenticated.
- **Chat screen** -- Textarea with Enter to send, Shift+Enter for newline. Streams responses via `fetch` + `ReadableStream`. Shows tool status spinners. Renders markdown on stream completion (not during -- avoids broken token artifacts).
- **Abort support** -- `AbortController` on fetch. Sending a new message cancels the in-progress stream.

### Step 5: Config

- `.env` with tool API keys
- `.gitignore`: `node_modules/`, `.env`, `.session.json`

## Key Patterns

### OAuth PKCE Flow
Full details in [oauth-reference.md](oauth-reference.md). Summary:
- Authorization: `https://auth.openai.com/oauth/authorize` with PKCE S256
- Token exchange: `https://auth.openai.com/oauth/token`
- Client ID: `app_EMoamEEZ73f0CkXaXp7hrann`
- Callback: `http://localhost:1455/auth/callback` (port is hardcoded by OpenAI)
- Tokens persist to `.session.json`, auto-refresh before expiry

### Responses API + Tool Loop
Full details in [responses-api.md](responses-api.md). Summary:
- Endpoint: `https://chatgpt.com/backend-api/codex/responses`
- User content type: `input_text`. Assistant content type: `output_text`.
- Stream events: `response.output_text.delta`, `response.output_item.done`
- After tool execution, input must include BOTH `function_call` items (with `id` starting with `fc_`) AND `function_call_output` items

### Adding Custom Tools
Full details in [tool-patterns.md](tool-patterns.md). Summary:
1. Add definition to `toolDefinitions` array in `tools.js`
2. Add execution `case` in `executeTool` switch
3. Add label in frontend `toolLabels` map

## Common Pitfalls

These are bugs we hit and resolved. Check these first when debugging.

| Problem | Cause | Fix |
|---------|-------|-----|
| `model is not supported` 400 error | Using `gpt-4o` on Codex backend | Use `gpt-5.4` or other supported model |
| `Unsupported tool type: web_search_preview` | Built-in tool types not supported | Implement web search as custom function tool |
| `Invalid value: 'input_text'` on assistant messages | Wrong content type for assistant role | Use `output_text` for assistant, `input_text` for user |
| `No tool call found for function call output` | Only sending `function_call_output` without the `function_call` | Include both in follow-up input |
| `Expected an ID that begins with 'fc'` | Using `call_id` as the `id` field | Capture `event.item.id` from stream, or generate `fc_` prefix |
| Fundamentals tool returns broken JSON | Naive string truncation at 30K chars | Use structural truncation (trim arrays/objects) or filter sections |
| `****` appears instead of bold | Parsing markdown mid-stream with incomplete tokens | Render plain text during streaming, markdown only on completion |
| CJS import error in ESM project | Named import from CommonJS module | `import pkg from "x"; const { fn } = pkg;` |
| Response cuts off mid-sentence | Default Express timeout too short for multi-tool calls | Set `req.setTimeout(5 * 60 * 1000)`, increase `server.keepAliveTimeout` |

## Supported Models (Codex Backend)

The `chatgpt.com/backend-api/codex/responses` endpoint supports:
- `gpt-5.5` -- strongest, complex tasks
- `gpt-5.4` -- recommended default for chat
- `gpt-5.4-mini` -- faster, lighter
- `gpt-5.3-codex` -- code-optimized
- `gpt-5.1-codex` -- older codex

Do NOT use `gpt-4o`, `gpt-4o-mini`, or other Platform API models.

## API Routes

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/auth/status` | Check if session is authenticated |
| POST | `/api/auth/login` | Start OAuth flow, return auth URL |
| POST | `/api/auth/logout` | Clear session and delete `.session.json` |
| POST | `/api/chat` | Send messages, stream response with tool execution |
