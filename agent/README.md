# Agent skills & MCP — equity-os

Version-controlled copies of Cursor/agent skills and MCP setup used with this repo. **No API keys** are stored here.

## Skills (in `agent/skills/`)

| Skill | Purpose |
|-------|---------|
| **stock-analysis** | EODHD fundamental analysis, scoring, strict JSON verdicts — aligns with `moonstocks-ai-analyzer` |
| **gpt-chatbot-website** | Codex / ChatGPT OAuth chat + tool calling — aligns with `web/codex_chat.py` |
| **supabase-postgres-best-practices** | Postgres/RDS tuning for `MOONSTOCKS_DATABASE_URL` |

The analyzer also ships a copy under `moonstocks-ai-analyzer/.claude/skills/stock-analysis/` (runtime). Prefer updating **both** when you change analysis rules.

## MCP servers

| Server | Config | Use |
|--------|--------|-----|
| **eodhd** | `agent/mcp/mcp.json.example` | Live fundamentals, prices, screening in Cursor |
| **cursor-ide-browser** | Built into Cursor | Test http://localhost:3000 |

See `agent/mcp/README.md` for EODHD setup. Tool names are listed in `agent/mcp/eodhd-tool-index.txt` (77 tools).

## Install on a new machine

```powershell
.\scripts\install-agent-assets.ps1
```

Then edit `%USERPROFILE%\.cursor\mcp.json` (or merge the example) and set your EODHD API key — never commit that file.

## Optional: global skills CLI

```bash
npx skills find postgres flask aws
npx skills add <package>
```

Browse: https://skills.sh/
