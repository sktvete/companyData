# Responses API Reference

The Codex Responses API lets ChatGPT subscribers use their subscription quota programmatically. It supports streaming, function calling (tool use), and multi-turn conversations.

## Endpoint

```
POST https://chatgpt.com/backend-api/codex/responses
```

**Headers:**
```
Content-Type: application/json
Authorization: Bearer <access_token>
```

## Request Body

```json
{
  "model": "gpt-5.4",
  "instructions": "System instructions here...",
  "stream": true,
  "store": false,
  "tools": [],
  "input": []
}
```

- `model` -- Must be a Codex-supported model (e.g. `gpt-5.4`, `gpt-5.5`). Do NOT use Platform API models like `gpt-4o`.
- `instructions` -- System prompt. Equivalent to a system message.
- `stream` -- Always `true` for real-time streaming.
- `store` -- Set `false` to avoid storing conversations on OpenAI's side.
- `tools` -- Array of function tool definitions (see [tool-patterns.md](tool-patterns.md)).
- `input` -- Array of message and tool-call items.

## Input Message Format

### User messages

```json
{
  "type": "message",
  "role": "user",
  "content": [{ "type": "input_text", "text": "Hello" }]
}
```

### Assistant messages

```json
{
  "type": "message",
  "role": "assistant",
  "content": [{ "type": "output_text", "text": "Hi there!" }]
}
```

**Critical:** User content uses `input_text`. Assistant content uses `output_text`. Using the wrong type causes a 400 error.

## Streaming Events

The response is an SSE stream. Key event types:

| Event Type | Purpose | Key Fields |
|------------|---------|------------|
| `response.output_text.delta` | Text chunk from assistant | `delta` (string) |
| `response.output_item.added` | New output item starts | `item.type`, `item.name`, `item.call_id` |
| `response.output_item.done` | Output item complete | `item` (full object with `id`, `arguments`) |
| `response.function_call_arguments.delta` | Streamed function call argument chunk | `delta`, `output_index` |
| `response.completed` | Full response complete | `response` |

### Parsing SSE

```javascript
const lines = chunk.split("\n");
for (const line of lines) {
  if (!line.startsWith("data: ")) continue;
  const data = line.slice(6).trim();
  if (!data || data === "[DONE]") continue;
  const event = JSON.parse(data);
  // handle event.type
}
```

### Collecting Text

```javascript
if (event.type === "response.output_text.delta" && event.delta) {
  clientRes.write(`data: ${JSON.stringify({ content: event.delta })}\n\n`);
}
```

## Tool Calling Loop

When GPT decides to call tools, the stream contains function call events instead of (or in addition to) text. The server must execute them and send results back.

### Flow

```
1. Send input to Responses API
2. Stream response
3. If function calls found:
   a. Execute all tools in parallel (Promise.all)
   b. Build follow-up input with function_call + function_call_output items
   c. Append follow-up to original input
   d. Go to step 1 (max 5 rounds)
4. If only text: stream to client, send [DONE]
```

### Collecting Function Calls from Stream

Track pending calls by `output_index`:

```javascript
const pendingCalls = {};

// When a function call item starts
if (event.type === "response.output_item.added" && event.item?.type === "function_call") {
  const idx = event.output_index ?? 0;
  pendingCalls[idx] = {
    name: event.item.name,
    callId: event.item.call_id,
    args: "",
  };
}

// Argument chunks stream in
if (event.type === "response.function_call_arguments.delta") {
  const idx = event.output_index ?? 0;
  if (!pendingCalls[idx]) pendingCalls[idx] = { args: "" };
  pendingCalls[idx].args += event.delta || "";
}

// When complete, capture the full item
if (event.type === "response.output_item.done" && event.item?.type === "function_call") {
  functionCalls.push({
    id: event.item.id,          // starts with "fc_"
    name: event.item.name,
    callId: event.item.call_id,
    arguments: JSON.parse(event.item.arguments || "{}"),
  });
}
```

### Building Follow-Up Input

Both `function_call` AND `function_call_output` items must be appended. Omitting either causes a 400 error.

```javascript
const followUp = [];

// 1. Add function_call items
for (const fc of functionCalls) {
  followUp.push({
    type: "function_call",
    id: fc.id || `fc_${crypto.randomBytes(12).toString("hex")}`,
    call_id: fc.callId,
    name: fc.name,
    arguments: JSON.stringify(fc.arguments),
  });
}

// 2. Execute tools in parallel
const results = await Promise.all(
  functionCalls.map(fc => executeTool(fc.name, fc.arguments))
);

// 3. Add function_call_output items
for (let i = 0; i < results.length; i++) {
  followUp.push({
    type: "function_call_output",
    call_id: functionCalls[i].callId,
    output: typeof results[i] === "string" ? results[i] : JSON.stringify(results[i]),
  });
}

// 4. Append to input and loop
currentInput = [...currentInput, ...followUp];
```

### ID Requirements

- `function_call.id` must start with `fc_`. Use `event.item.id` from the stream (it already has this prefix). If missing, generate one: `fc_${crypto.randomBytes(12).toString("hex")}`.
- `function_call.call_id` and `function_call_output.call_id` must match.

## Timeouts

Multi-tool calls can take 30+ seconds. Set generous timeouts:

```javascript
req.setTimeout(5 * 60 * 1000);
res.setTimeout(5 * 60 * 1000);
res.setHeader("X-Accel-Buffering", "no"); // prevents proxy buffering
```

On the server:
```javascript
server.keepAliveTimeout = 5 * 60 * 1000;
server.headersTimeout = 5 * 60 * 1000 + 1000;
```

## Frontend Streaming

Use `fetch` with `ReadableStream` to consume SSE:

```javascript
const res = await fetch("/api/chat", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ messages }),
  signal: abortController.signal,
});

const reader = res.body.getReader();
const decoder = new TextDecoder();

while (true) {
  const { value, done } = await reader.read();
  if (done) break;
  const chunk = decoder.decode(value, { stream: true });
  // parse SSE lines from chunk
}
```

### Markdown Rendering

Render plain text (`textContent`) during streaming. Apply `marked.parse()` only after the stream completes. Parsing markdown mid-stream causes broken formatting (e.g. `****` instead of bold) because tokens may be split across chunks.
