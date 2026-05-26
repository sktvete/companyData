/** ChatGPT OAuth session stored in this browser (localStorage). Favorites use MoonUser separately. */
window.CodexAuth = (function () {
  const STORAGE_KEY = 'ms_codex_session';
  let loginPoll = null;

  function normalizeSession(raw) {
    if (!raw || typeof raw !== 'object') return null;
    const s = {
      accessToken: raw.accessToken || raw.access_token || null,
      refreshToken: raw.refreshToken || raw.refresh_token || null,
      expiresAt: Number(raw.expiresAt || raw.expires_at || 0),
      accountId: raw.accountId || raw.account_id || null,
    };
    return s.accessToken ? s : null;
  }

  function load() {
    try {
      return normalizeSession(JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null'));
    } catch (_) {
      return null;
    }
  }

  function save(session) {
    const s = normalizeSession(session);
    if (!s) return;
    localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
  }

  function clear() {
    localStorage.removeItem(STORAGE_KEY);
  }

  function isAuthenticated() {
    const s = load();
    if (!s) return false;
    if (s.refreshToken) return true;
    return s.expiresAt > Date.now() / 1000 - 30;
  }

  function status() {
    const s = load();
    return {
      authenticated: isAuthenticated(),
      accountId: s?.accountId || null,
      loginInProgress: false,
    };
  }

  function stopPoll() {
    if (loginPoll) {
      clearInterval(loginPoll);
      loginPoll = null;
    }
  }

  async function refreshIfNeeded() {
    const s = load();
    if (!s) return null;
    if (s.expiresAt > Date.now() / 1000 + 60) return s;
    if (!s.refreshToken) {
      clear();
      return null;
    }
    const r = await fetch('/api/auth/codex/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ codex_session: s }),
    });
    const d = await r.json();
    if (!r.ok) {
      clear();
      return null;
    }
    save(d.session);
    return load();
  }

  async function getSessionForRequest() {
    return refreshIfNeeded();
  }

  async function appendToBody(body) {
    const s = await getSessionForRequest();
    if (s) body.codex_session = s;
    return body;
  }

  async function claimOnce() {
    const r = await fetch('/api/auth/codex/claim');
    const d = await r.json();
    if (d.session) {
      save(d.session);
      stopPoll();
      return true;
    }
    if (d.error) throw new Error(d.error);
    return false;
  }

  async function login() {
    if (isAuthenticated()) return load();
    stopPoll();
    const r = await fetch('/api/auth/login', { method: 'POST' });
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    if (!d.authUrl) throw new Error('No auth URL');
    window.open(d.authUrl, 'chatgpt_oauth', 'width=520,height=720');
    return new Promise((resolve, reject) => {
      const deadline = Date.now() + 300000;
      loginPoll = setInterval(async () => {
        if (Date.now() > deadline) {
          stopPoll();
          reject(new Error('Login timed out'));
          return;
        }
        try {
          if (await claimOnce()) {
            stopPoll();
            notifyChanged();
            resolve(load());
          }
        } catch (e) {
          stopPoll();
          reject(e);
        }
      }, 1200);
    });
  }

  async function logout() {
    stopPoll();
    clear();
    try { await fetch('/api/auth/codex-logout', { method: 'POST' }); } catch (_) {}
  }

  async function loginInProgress() {
    try {
      const r = await fetch('/api/auth/codex/status');
      const d = await r.json();
      return !!d.loginInProgress;
    } catch (_) {
      return false;
    }
  }

  function notifyChanged() {
    document.dispatchEvent(new CustomEvent('codexauth:changed'));
  }

  async function resumeIfPending() {
    if (isAuthenticated()) return true;
    const pending = await loginInProgress();
    if (!pending || loginPoll) return pending;
    loginPoll = setInterval(async () => {
      try {
        if (await claimOnce()) {
          stopPoll();
          notifyChanged();
        } else if (!(await loginInProgress())) {
          stopPoll();
        }
      } catch (_) {
        stopPoll();
      }
    }, 1200);
    return true;
  }

  return {
    load,
    save,
    clear,
    isAuthenticated,
    status,
    getSessionForRequest,
    appendToBody,
    login,
    logout,
    refreshIfNeeded,
    loginInProgress,
    resumeIfPending,
    stopPoll,
  };
})();
