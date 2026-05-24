# Tool Patterns Reference

How to define, execute, and display custom tools in the chatbot.

## Tool Definition Schema

Each tool follows the Responses API function tool format:

```json
{
  "type": "function",
  "name": "tool_name",
  "description": "What the tool does and when to use it.",
  "parameters": {
    "type": "object",
    "properties": {
      "param1": { "type": "string", "description": "..." },
      "param2": { "type": "number", "description": "..." }
    },
    "required": ["param1"]
  }
}
```

Export all definitions as an array:

```javascript
export const toolDefinitions = [
  { type: "function", name: "web_search", ... },
  { type: "function", name: "get_live_price", ... },
  // ...
];
```

## Adding a New Tool

Three steps:

### 1. Define in `toolDefinitions`

Add the function definition object to the array. Write clear descriptions -- GPT uses them to decide when to call the tool.

### 2. Add execution in `executeTool`

```javascript
export async function executeTool(name, args) {
  switch (name) {
    case "your_new_tool": {
      // Call external API, process data, return result
      const result = await someApi(args.param1);
      return result;
    }
    // ... other cases
    default:
      return { error: `Unknown tool: ${name}` };
  }
}
```

Return a JSON-serializable value. The server stringifies it before sending back to GPT.

### 3. Add frontend label

In `public/app.js`, add a display label:

```javascript
const toolLabels = {
  web_search: "Searching the web",
  your_new_tool: "Doing the thing",
};
```

## Web Search Pattern (No API Key)

Uses `duckduckgo-search` npm package for server-side search:

```javascript
import pkg from "duckduckgo-search";
const { search } = pkg;

case "web_search": {
  const results = await search(args.query, { maxResults: 8 });
  return results.map(r => ({
    title: r.title,
    url: r.url,
    snippet: r.description,
  }));
}
```

Note the CJS import pattern: `import pkg from "x"; const { fn } = pkg;` -- required because `duckduckgo-search` is a CommonJS module used in an ESM project.

The built-in `web_search_preview` tool type is NOT supported by the Codex Responses API. Always implement web search as a custom function tool.

## REST API Wrapper Pattern (EODHD Example)

For any REST API, create a reusable wrapper:

```javascript
const EODHD_BASE = "https://eodhd.com/api";

async function eodhd(path, params = {}, skipTruncate = false) {
  const token = process.env.EODHD_API_KEY;
  if (!token) return { error: "API key not configured" };

  const url = new URL(`${EODHD_BASE}/${path}`);
  url.searchParams.set("api_token", token);
  url.searchParams.set("fmt", "json");
  for (const [k, v] of Object.entries(params)) {
    if (v != null && v !== "") url.searchParams.set(k, String(v));
  }

  const res = await fetch(url.toString());
  if (!res.ok) return { error: `API error ${res.status}` };
  const data = await res.json();

  if (skipTruncate) return data;

  const json = JSON.stringify(data);
  if (json.length > 25000) return truncateData(data, 25000);
  return data;
}
```

Each tool maps to an API endpoint:

```javascript
case "get_live_price":
  return await eodhd(`real-time/${args.ticker}`, {
    s: args.additional_symbols,
  });

case "get_historical_prices":
  return await eodhd(`eod/${args.ticker}`, {
    from: args.start_date,
    to: args.end_date,
    period: args.period || "d",
    order: "d",
  });
```

## Handling Large Responses

Some APIs return massive payloads (e.g. EODHD fundamentals can be 900KB+). Two strategies:

### 1. Domain-Specific Cleaning

Strip irrelevant sections before returning. For EODHD fundamentals:

```javascript
function cleanFundamentals(data) {
  const clean = { ...data };
  // Keep only useful General fields, trim Description
  // Keep last 8 quarterly earnings, last 3 annual
  // Keep last 4 quarterly financials per statement
  // Drop: Holders, InsiderTransactions, outstandingShares, ESGScores, Officers
  return clean;
}
```

### 2. Structural Truncation

A generic fallback that preserves valid JSON:

```javascript
function truncateData(data, maxLen) {
  if (Array.isArray(data)) {
    const arr = [...data];
    while (arr.length > 1 && JSON.stringify(arr).length > maxLen) {
      arr.pop();
    }
    return arr;
  }

  if (typeof data === "object" && data !== null) {
    const result = {};
    let currentLen = 2; // {}
    for (const key of Object.keys(data)) {
      const valStr = JSON.stringify(data[key]);
      if (currentLen + key.length + valStr.length + 4 > maxLen) {
        result._truncated = `${remaining} fields omitted`;
        break;
      }
      result[key] = data[key];
      currentLen += key.length + valStr.length + 4;
    }
    return result;
  }

  return data;
}
```

Never use naive string slicing (`JSON.stringify(data).slice(0, N)`) -- it produces invalid JSON.

## Frontend Tool Status

Show spinners while tools execute, remove them when done:

```javascript
// When tool starts
function showToolStatus(bubble, toolName) {
  const el = document.createElement("div");
  el.className = "tool-status";
  el.id = `tool-${toolName}`;
  el.textContent = `${toolLabels[toolName] || toolName}...`;
  bubble.prepend(el);
}

// When tool completes
function removeToolStatus(toolName) {
  document.getElementById(`tool-${toolName}`)?.remove();
}
```

The SSE stream sends `{ tool: "name", status: "running" }` and `{ tool: "name", status: "done" }` events that the frontend uses to manage these indicators.

## Parallel Execution

All tool calls from a single GPT response are executed in parallel using `Promise.all`. This is critical for performance -- stock analysis can trigger 6+ tool calls simultaneously:

```javascript
const results = await Promise.all(
  functionCalls.map(async (fc) => {
    const result = await executeTool(fc.name, fc.arguments);
    return { callId: fc.callId, output: JSON.stringify(result) };
  })
);
```

Sequential execution would take 6x longer.

## Complete Tool List (Current Implementation)

| Tool | API | Purpose |
|------|-----|---------|
| `web_search` | DuckDuckGo | Real-time web search, no API key |
| `search_stocks` | EODHD | Find ticker symbols by name/ISIN |
| `get_live_price` | EODHD | Current price snapshot (~15min delay) |
| `get_historical_prices` | EODHD | Daily/weekly/monthly OHLCV data |
| `get_fundamentals` | EODHD | Financials, valuation, earnings, analyst ratings |
| `get_company_news` | EODHD | Recent financial news articles |
| `get_sentiment` | EODHD | News/social media sentiment scores |
| `get_technical_indicator` | EODHD | SMA, RSI, MACD, Bollinger, etc. |
| `get_upcoming_earnings` | EODHD | Upcoming earnings dates and estimates |
