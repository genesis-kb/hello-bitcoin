/**
 * app.js — shared utilities for Programming Bitcoin OJ
 * Handles: auth token storage, authenticated fetch, nav rendering
 */

const API = '/api';

// ── Token management ──────────────────────────────────────────────────────────
const Auth = {
  getAccess: () => localStorage.getItem('access_token'),
  getRefresh: () => localStorage.getItem('refresh_token'),
  set(access, refresh) {
    localStorage.setItem('access_token', access);
    if (refresh) localStorage.setItem('refresh_token', refresh);
  },
  clear() {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    localStorage.removeItem('current_user');
  },
  isLoggedIn: () => !!localStorage.getItem('access_token'),
  getUser() {
    const raw = localStorage.getItem('current_user');
    return raw ? JSON.parse(raw) : null;
  },
  setUser(u) { localStorage.setItem('current_user', JSON.stringify(u)); },
};

// ── Authenticated fetch (auto-refresh on 401) ─────────────────────────────────
async function apiFetch(path, opts = {}) {
  const token = Auth.getAccess();
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  let res = await fetch(API + path, { ...opts, headers });

  if (res.status === 401) {
    Auth.clear();
    redirectToLogin();
    throw new Error('Session expired');
  }

  return res;
}

async function apiGet(path) { return apiFetch(path); }
async function apiPost(path, body) { return apiFetch(path, { method: 'POST', body: JSON.stringify(body) }); }
async function apiPut(path, body) { return apiFetch(path, { method: 'PUT', body: JSON.stringify(body) }); }
async function apiDelete(path) { return apiFetch(path, { method: 'DELETE' }); }

// ── Navigation helpers ────────────────────────────────────────────────────────
function redirectToLogin(next = '') {
  const url = `/login.html${next ? '?next=' + encodeURIComponent(next) : ''}`;
  window.location.href = url;
}

function requireAuth() {
  if (!Auth.isLoggedIn()) redirectToLogin(window.location.pathname + window.location.search);
}

function requireAdmin() {
  const user = Auth.getUser();
  if (!user || user.role !== 'admin') { window.location.href = '/index.html'; }
}

async function loadCurrentUser() {
  if (!Auth.isLoggedIn()) return null;
  const cached = Auth.getUser();
  if (cached) return cached;
  const res = await apiGet('/auth/me');
  if (res.ok) {
    const user = await res.json();
    Auth.setUser(user);
    return user;
  }
  return null;
}

const NAV_LINK =
  'text-sm text-zinc-400 hover:text-zinc-100 transition-colors no-underline hover:no-underline';
const NAV_LINK_ACTIVE =
  'text-sm text-amber-400 font-medium no-underline';

// ── Render shared nav ─────────────────────────────────────────────────────────
async function renderNav(activePage = '') {
  const nav = document.getElementById('nav-links');
  const userEl = document.getElementById('nav-user');
  if (!nav) return;

  const user = await loadCurrentUser();

  const links = [
    { href: '/index.html', label: 'Problems', key: 'problems' },
    { href: '/submissions.html', label: 'Submissions', key: 'submissions' },
  ];
  if (user?.role === 'admin') {
    links.push({ href: '/admin/index.html', label: 'Admin', key: 'admin' });
  }

  nav.innerHTML = links.map(l =>
    `<a href="${l.href}" class="${activePage === l.key ? NAV_LINK_ACTIVE : NAV_LINK}">${l.label}</a>`
  ).join('');

  if (userEl) {
    if (user) {
      userEl.innerHTML = `
        <span class="text-sm text-zinc-300"><span class="font-medium text-zinc-100">${escHtml(user.username)}</span></span>
        <a href="#" id="logout-btn" class="ml-3 text-xs text-red-400 hover:text-red-300 no-underline">Logout</a>`;
      document.getElementById('logout-btn').addEventListener('click', e => {
        e.preventDefault();
        Auth.clear();
        window.location.href = '/login.html';
      });
    } else {
      userEl.innerHTML = `<a href="/login.html" class="text-sm font-medium text-amber-400 hover:text-amber-300 no-underline">Login</a>`;
    }
  }
}

// ── Verdict helpers ───────────────────────────────────────────────────────────
const BADGE_BASE =
  'inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-semibold uppercase tracking-wide';

function verdictBadge(verdict, status) {
  if (!verdict && status === 'PENDING')
    return `<span class="${BADGE_BASE} bg-zinc-700/40 text-zinc-400">Pending</span>`;
  if (!verdict && status === 'JUDGING')
    return `<span class="${BADGE_BASE} bg-amber-500/15 text-amber-400">Judging</span>`;
  const map = {
    AC: 'bg-emerald-500/15 text-emerald-400',
    WA: 'bg-red-500/15 text-red-400',
    TLE: 'bg-amber-500/15 text-amber-400',
    RE: 'bg-orange-500/15 text-orange-400',
    CE: 'bg-blue-500/15 text-blue-400',
  };
  const cls = map[verdict] || 'bg-zinc-700/40 text-zinc-400';
  return `<span class="${BADGE_BASE} ${cls}">${verdict}</span>`;
}

function verdictBoxClass(verdict) {
  const map = {
    AC: 'border-emerald-500/40 bg-emerald-500/5',
    WA: 'border-red-500/40 bg-red-500/5',
    TLE: 'border-amber-500/40 bg-amber-500/5',
    RE: 'border-orange-500/40 bg-orange-500/5',
    CE: 'border-blue-500/40 bg-blue-500/5',
  };
  return map[verdict] || 'border-zinc-700 bg-zinc-900/50';
}

function verdictClass(verdict) {
  return verdictBoxClass(verdict);
}

// ── UI class helpers (for dynamic JS) ─────────────────────────────────────────
const CHAPTER_BTN_ACTIVE =
  'chapter-btn px-3 py-1.5 rounded-full border text-xs font-medium transition border-amber-500/50 bg-amber-500/10 text-amber-400';
const CHAPTER_BTN_INACTIVE =
  'chapter-btn px-3 py-1.5 rounded-full border text-xs font-medium transition border-zinc-700/80 text-zinc-500 hover:border-amber-500/30 hover:text-zinc-300 bg-transparent';

function setChapterFilterActive(activeBtn) {
  document.querySelectorAll('.chapter-btn').forEach(b => {
    b.className = b === activeBtn ? CHAPTER_BTN_ACTIVE : CHAPTER_BTN_INACTIVE;
  });
}

// ── Misc ─────────────────────────────────────────────────────────────────────
function fmtDate(iso) {
  return new Date(iso).toLocaleString();
}

function escHtml(str) {
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
