# MCP configuration

## EODHD (required for agent + optional Claude analyzer path)

Official MCP endpoint (API key in URL — **keep out of git**):

```
https://mcpv2.eodhd.dev/v1/mcp?apikey=YOUR_EODHD_API_KEY
```

1. Copy `mcp.json.example` to your user config:

   ```powershell
   Copy-Item agent\mcp\mcp.json.example $env:USERPROFILE\.cursor\mcp.json
   ```

2. Replace `YOUR_EODHD_API_KEY` with the same key as `EODHD_API_KEY` in `.env`.

3. Restart Cursor (or reload MCP servers).

Cursor exposes this server as **`user-eodhd`** / **`eodhd`** in the agent. The analyzer OpenAI path uses REST (`eodhd_fetch.py`) instead of MCP; Claude SDK path can use MCP per `moonstocks-ai-analyzer/.claude/skills/stock-analysis/`.

## cursor-ide-browser

Shipped with Cursor — no repo config. Use to verify company pages, screener, and Moonstocks trigger flows on port 3000.

## Security

- Do **not** commit `~/.cursor/mcp.json` with a real key.
- If a key was ever committed, rotate it at https://eodhd.com/
