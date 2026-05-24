# OAuth PKCE Reference

OpenAI uses a standard OAuth 2.0 PKCE flow to authenticate ChatGPT subscribers. No client secret is needed.

## Constants

```javascript
const AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize";
const TOKEN_URL     = "https://auth.openai.com/oauth/token";
const CLIENT_ID     = "app_EMoamEEZ73f0CkXaXp7hrann";
const REDIRECT_URI  = "http://localhost:1455/auth/callback";
const SCOPES        = "openid profile email offline_access";
```

- The **redirect URI** uses port 1455 -- this is hardcoded in OpenAI's OAuth app registration. You cannot change it.
- `offline_access` scope is required to receive a refresh token.

## PKCE Helpers

```javascript
import crypto from "crypto";

function generateVerifier() {
  return crypto.randomBytes(32).toString("base64url");
}

function generateChallenge(verifier) {
  return crypto.createHash("sha256").update(verifier).digest("base64url");
}

function generateState() {
  return crypto.randomBytes(16).toString("hex");
}
```

## Authorization URL

Build the full URL with these query parameters:

| Parameter | Value |
|-----------|-------|
| `response_type` | `code` |
| `client_id` | `app_EMoamEEZ73f0CkXaXp7hrann` |
| `redirect_uri` | `http://localhost:1455/auth/callback` |
| `scope` | `openid profile email offline_access` |
| `code_challenge` | SHA-256 of verifier, base64url-encoded |
| `code_challenge_method` | `S256` |
| `state` | Random hex string |
| `id_token_add_organizations` | `true` |
| `codex_cli_simplified_flow` | `true` |

## Callback Server

A temporary HTTP server on port 1455 catches the redirect:

1. Validate `state` matches expected value
2. Extract `code` from query params
3. Return a success HTML page to the user
4. Resolve the `code` to the waiting promise
5. Shut down after 1 second

Set a 5-minute timeout on the callback server to avoid hanging indefinitely.

## Token Exchange

```javascript
const res = await fetch(TOKEN_URL, {
  method: "POST",
  headers: { "Content-Type": "application/x-www-form-urlencoded" },
  body: new URLSearchParams({
    grant_type: "authorization_code",
    client_id: CLIENT_ID,
    code,
    code_verifier: verifier,
    redirect_uri: REDIRECT_URI,
  }),
});

const data = await res.json();
// data.access_token, data.refresh_token, data.expires_in (seconds)
```

## Token Refresh

```javascript
const res = await fetch(TOKEN_URL, {
  method: "POST",
  headers: { "Content-Type": "application/x-www-form-urlencoded" },
  body: new URLSearchParams({
    grant_type: "refresh_token",
    refresh_token: session.refreshToken,
    client_id: CLIENT_ID,
  }),
});
```

Call `ensureValidToken()` before every API request. Refresh if the token expires within 60 seconds:

```javascript
async function ensureValidToken() {
  if (!session.accessToken) throw new Error("Not authenticated");
  if (Date.now() > session.expiresAt - 60_000) {
    await refreshAccessToken();
  }
}
```

## Account ID Extraction

The access token is a JWT. The account ID is in the `https://api.openai.com/auth` claim:

```javascript
function extractAccountId(accessToken) {
  const payload = JSON.parse(
    Buffer.from(accessToken.split(".")[1], "base64url").toString("utf8")
  );
  return payload["https://api.openai.com/auth"]?.chatgpt_account_id || null;
}
```

## Session Persistence

Save the full session (tokens + expiry + account ID) to `.session.json`:

```javascript
const SESSION_FILE = join(__dirname, ".session.json");

function saveSession() {
  fs.writeFileSync(SESSION_FILE, JSON.stringify(session, null, 2));
}

function loadSession() {
  try {
    return JSON.parse(fs.readFileSync(SESSION_FILE, "utf8"));
  } catch {
    return { accessToken: null, refreshToken: null, expiresAt: 0, accountId: null };
  }
}
```

Always add `.session.json` to `.gitignore`.

## Frontend Auth Flow

1. User clicks "Sign in with ChatGPT"
2. Frontend `POST /api/auth/login` -- server returns `{ authUrl }` and starts callback server
3. Frontend opens `authUrl` in a popup/new tab
4. User authenticates on `auth.openai.com`
5. Redirect hits `localhost:1455/auth/callback` with code
6. Server exchanges code for tokens, saves session
7. Frontend polls `GET /api/auth/status` until `{ authenticated: true }`
8. Frontend switches to chat view
