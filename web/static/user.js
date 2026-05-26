/** Moonstocks sign-in + server-backed favorites (per user, SQLite/Postgres). */
window.MoonUser = (function () {
  const FAV = { symbol: new Set(), investor: new Set() };
  const DEMO_USERS = [
    { slug: 'sindre', label: 'Sindre' },
    { slug: 'ask', label: 'Ask' },
    { slug: 'test', label: 'Test' },
    { slug: 'alexander', label: 'Alexander' },
  ];
  let user = null;

  async function readJson(r) {
    const text = await r.text();
    if (!text) return {};
    try {
      return JSON.parse(text);
    } catch {
      throw new Error(r.ok ? 'Invalid server response' : (`HTTP ${r.status}: ${text.slice(0, 120)}`));
    }
  }

  function isLoggedIn() {
    return !!(user && user.userSignedIn);
  }

  function isFav(kind, key) {
    if (!key) return false;
    const k = kind === 'symbol' ? String(key).toUpperCase() : String(key);
    return FAV[kind]?.has(k) || false;
  }

  function starBtn(kind, key, extraClass) {
    const on = isFav(kind, key);
    const cls = 'ms-star' + (on ? ' on' : '') + (extraClass ? ' ' + extraClass : '');
    const title = on ? 'Remove from favorites' : 'Add to favorites';
    return `<button type="button" class="${cls}" data-fav-kind="${kind}" data-fav-key="${key}" title="${title}" aria-label="${title}">${on ? '★' : '☆'}</button>`;
  }

  function closeUserMenu() {
    document.getElementById('msUserDropdown')?.setAttribute('hidden', '');
    document.getElementById('msLoginBtn')?.setAttribute('aria-expanded', 'false');
    document.getElementById('msUserBtn')?.setAttribute('aria-expanded', 'false');
  }

  function toggleUserMenu() {
    const menu = document.getElementById('msUserDropdown');
    const btn = document.getElementById('msLoginBtn') || document.getElementById('msUserBtn');
    if (!menu || !btn) return;
    const open = menu.hasAttribute('hidden');
    if (open) {
      menu.removeAttribute('hidden');
      btn.setAttribute('aria-expanded', 'true');
    } else {
      closeUserMenu();
    }
  }

  async function refreshAuth() {
    try {
      const r = await fetch('/api/auth/status');
      user = await readJson(r);
    } catch {
      user = { authenticated: false, userSignedIn: false };
    }
    if (user.userSignedIn) await loadFavorites();
    else {
      FAV.symbol.clear();
      FAV.investor.clear();
    }
    renderNav();
    document.dispatchEvent(new CustomEvent('moonuser:auth', { detail: user }));
    return user;
  }

  async function loadFavorites() {
    if (!isLoggedIn()) return;
    try {
      const r = await fetch('/api/favorites');
      if (!r.ok) return;
      const d = await readJson(r);
      FAV.symbol.clear();
      FAV.investor.clear();
      (d.favorites || []).forEach(f => {
        const kind = f.kind;
        const key = kind === 'symbol' ? f.item_key.toUpperCase() : f.item_key;
        if (FAV[kind]) FAV[kind].add(key);
      });
    } catch (_) {}
    document.dispatchEvent(new CustomEvent('moonuser:favorites'));
  }

  async function loginDemo(slug) {
    closeUserMenu();
    try {
      const r = await fetch('/api/auth/demo-login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user: slug }),
      });
      const d = await readJson(r);
      if (!r.ok) throw new Error(d.error || 'Sign in failed');
      user = d;
      await loadFavorites();
      renderNav();
      document.dispatchEvent(new CustomEvent('moonuser:auth', { detail: user }));
    } catch (e) {
      alert(String(e.message || e));
    }
  }

  function openSignInMenu() {
    if (isLoggedIn()) return;
    toggleUserMenu();
  }

  async function logout() {
    closeUserMenu();
    await fetch('/api/auth/logout', { method: 'POST' });
    user = { authenticated: false, userSignedIn: false };
    FAV.symbol.clear();
    FAV.investor.clear();
    renderNav();
    document.dispatchEvent(new CustomEvent('moonuser:auth', { detail: user }));
    document.dispatchEvent(new CustomEvent('moonuser:favorites'));
  }

  async function toggleFavorite(kind, key) {
    if (!isLoggedIn()) {
      openSignInMenu();
      return false;
    }
    const norm = kind === 'symbol' ? String(key).toUpperCase() : String(key);
    const was = isFav(kind, norm);
    if (was) {
      await fetch(`/api/favorites/${encodeURIComponent(kind)}/${encodeURIComponent(norm)}`, { method: 'DELETE' });
      FAV[kind].delete(norm);
    } else {
      await fetch('/api/favorites', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kind, key: norm }),
      });
      FAV[kind].add(norm);
    }
    document.dispatchEvent(new CustomEvent('moonuser:favorites'));
    if (isLoggedIn()) {
      const n = FAV.symbol.size + FAV.investor.size;
      user = { ...user, favoritesCount: n };
      renderNav();
    }
    return !was;
  }

  function bindNavEvents() {
    document.getElementById('msLoginBtn')?.addEventListener('click', e => {
      e.stopPropagation();
      toggleUserMenu();
    });
    document.getElementById('msUserBtn')?.addEventListener('click', e => {
      e.stopPropagation();
      toggleUserMenu();
    });
    document.querySelectorAll('.ms-user-option[data-demo-user]').forEach(btn => {
      btn.addEventListener('click', e => {
        e.stopPropagation();
        loginDemo(btn.dataset.demoUser);
      });
    });
    document.getElementById('msLogoutBtn')?.addEventListener('click', e => {
      e.stopPropagation();
      logout();
    });
  }

  function renderNav() {
    const el = document.getElementById('msUserNav');
    if (!el) return;
    if (isLoggedIn()) {
      const n = (user.favoritesCount != null ? user.favoritesCount : FAV.symbol.size + FAV.investor.size);
      const name = user.displayName || 'Signed in';
      el.innerHTML = `<div class="ms-user-menu" id="msUserMenu">`
        + `<button type="button" class="ms-user-trigger" id="msUserBtn" aria-haspopup="true" aria-expanded="false" title="Account">`
        + `<span class="ms-user-label">${name}</span>`
        + `<span class="ms-user-fav-count">${n} ★</span>`
        + `</button>`
        + `<div class="ms-user-dropdown" id="msUserDropdown" hidden role="menu">`
        + `<button type="button" class="ms-user-option" role="menuitem" id="msLogoutBtn">Sign out</button>`
        + `</div></div>`;
    } else {
      el.innerHTML = `<div class="ms-user-menu" id="msUserMenu">`
        + `<button type="button" class="ms-nav-btn ms-nav-btn-primary" id="msLoginBtn" aria-haspopup="true" aria-expanded="false">Sign in</button>`
        + `<div class="ms-user-dropdown" id="msUserDropdown" hidden role="menu">`
        + DEMO_USERS.map(u => `<button type="button" class="ms-user-option" role="menuitem" data-demo-user="${u.slug}">${u.label}</button>`).join('')
        + `</div></div>`;
    }
    bindNavEvents();
  }

  document.addEventListener('click', e => {
    if (!e.target.closest('#msUserMenu')) closeUserMenu();

    const btn = e.target.closest('.ms-star');
    if (!btn) return;
    e.preventDefault();
    e.stopPropagation();
    toggleFavorite(btn.dataset.favKind, btn.dataset.favKey).then(on => {
      btn.textContent = on ? '★' : '☆';
      btn.classList.toggle('on', on);
      btn.title = on ? 'Remove from favorites' : 'Add to favorites';
    });
  });

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeUserMenu();
  });

  document.addEventListener('DOMContentLoaded', () => refreshAuth());

  return {
    refreshAuth,
    loadFavorites,
    loginDemo,
    openSignInMenu,
    logout,
    isLoggedIn,
    isFav,
    starBtn,
    toggleFavorite,
  };
})();
