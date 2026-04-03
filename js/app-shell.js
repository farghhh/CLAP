/**
 * CLAP — Shared App Shell
 * Injects sidebar + topbar. No loader on inner pages.
 */
'use strict';

const AppShell = {
  init(activePage, opts = {}) {
    // CLAP.Auth.requireAuth(); // ← uncomment when backend is ready
    this._injectSidebar(activePage);
    this._injectTopbar(opts);
    CLAP.initSidebar();
    this._injectLogoutHandler();
  },

  _injectSidebar(activePage) {
    const navItems = [
      { page: 'dashboard.html',        icon: this._icons.dashboard,   label: 'Dashboard' },
      { page: 'assignments.html',      icon: this._icons.assignments, label: 'My Assignments' },
      { page: 'schedule.html',         icon: this._icons.schedule,    label: 'Schedule' },
      { page: 'stress-analytics.html', icon: this._icons.stress,      label: 'Stress Analytics' },
      { page: 'settings.html',         icon: this._icons.settings,    label: 'Settings' },
    ];

    const el = document.getElementById('sidebar');
    if (!el) return;

    const user = CLAP.Auth.getUser() || {};
    const name = user.name || 'Student';

    el.innerHTML = `
      <div class="sidebar-logo" aria-label="CLAP">
        <img src="assets/logo.png" alt="CLAP" onerror="this.style.display='none'"
             style="width:120px;height:120px;object-fit:contain;margin: 0 auto;" />
      </div>

      <nav class="sidebar-nav" aria-label="Main navigation" role="navigation">
        ${navItems.map(item => `
          <a href="${item.page}"
             class="nav-item ${item.page === activePage ? 'active' : ''}"
             aria-current="${item.page === activePage ? 'page' : 'false'}"
             aria-label="${item.label}">
            <span class="nav-icon" aria-hidden="true">${item.icon}</span>
            <span>${item.label}</span>
          </a>
        `).join('')}
      </nav>

      <div class="sidebar-divider" role="separator"></div>

      <div class="sidebar-logout">
        <button class="nav-item logout-nav-btn" id="logout-btn" type="button"
                style="width:100%;border:none;background:none;cursor:pointer;"
                aria-label="Log out of CLAP">
          <span class="nav-icon" aria-hidden="true">${this._icons.logout}</span>
          <span>Log Out</span>
        </button>
      </div>
    `;

    /* Logout confirmation modal — create only once */
    if (!document.getElementById('logout-modal')) {
      const modal = document.createElement('div');
      modal.id = 'logout-modal';
      modal.style.cssText = `
        display:none;position:fixed;inset:0;z-index:9000;
        background:rgba(26,58,92,0.35);backdrop-filter:blur(4px);
        align-items:center;justify-content:center;
      `;
      modal.innerHTML = `
        <div style="background:#fff;border-radius:20px;padding:40px;
                    max-width:420px;width:90%;text-align:center;
                    box-shadow:0 20px 60px rgba(26,58,92,0.2);animation:modalIn 0.25s ease both;">
          <h2 style="font-family:var(--font-heading);font-size:1.4rem;font-weight:700;
                     color:var(--text-primary);margin-bottom:12px;">Logout Confirmation</h2>
          <p style="color:var(--text-muted);font-size:0.9rem;margin-bottom:32px;">
            Are you sure you want to log out?
          </p>
          <div style="display:flex;gap:16px;justify-content:center;">
            <button id="logout-confirm-btn"
                    style="flex:1;max-width:160px;padding:12px 24px;border-radius:999px;
                           background:var(--grad-primary);color:#fff;border:none;cursor:pointer;
                           font-family:var(--font-heading);font-weight:700;font-size:0.9rem;">
              Confirm
            </button>
            <button id="logout-cancel-btn"
                    style="flex:1;max-width:160px;padding:12px 24px;border-radius:999px;
                           background:transparent;color:var(--clap-teal);border:2px solid var(--clap-teal);
                           cursor:pointer;font-family:var(--font-heading);font-weight:700;font-size:0.9rem;">
              Cancel
            </button>
          </div>
        </div>
      `;
      document.body.appendChild(modal);
    }
  },

  _injectTopbar(opts = {}) {
    const el = document.getElementById('topbar');
    if (!el) return;
    const user  = CLAP.Auth.getUser() || {};
    const name  = user.name || 'Student';
    const first = name.split(' ')[0];

    const searchHtml = opts.showSearch ? `
      <div class="topbar-search" role="search">
        <span class="search-icon" aria-hidden="true">
          <svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24">
            <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
          </svg>
        </span>
        <input type="search" id="topbar-search-input" placeholder="Search…"
               autocomplete="off" aria-label="Search" />
      </div>` : '';

    el.innerHTML = `
      <div class="topbar-user">
        <div class="topbar-avatar" aria-hidden="true"
             style="width:52px;height:52px;border-radius:50%;overflow:hidden;
                    background:var(--bg-light);display:flex;align-items:center;
                    justify-content:center;font-family:var(--font-heading);
                    font-weight:800;font-size:1.3rem;color:var(--clap-teal);
                    border:3px solid var(--clap-teal-light);flex-shrink:0;">
          ${name.charAt(0).toUpperCase()}
        </div>
        <div class="topbar-greeting">
          <h2>Welcome Back, ${first}!</h2>
          <p>Nice to have you back.</p>
        </div>
      </div>
      ${searchHtml}
    `;

    /* Wire up topbar search to dispatch a custom event pages can listen to */
    if (opts.showSearch) {
      const searchInput = document.getElementById('topbar-search-input');
      if (searchInput) {
        searchInput.addEventListener('input', (e) => {
          document.dispatchEvent(new CustomEvent('clap:search', {
            detail: e.target.value.toLowerCase()
          }));
        });
      }
    }
  },

  _injectLogoutHandler() {
    const btn     = document.getElementById('logout-btn');
    const modal   = document.getElementById('logout-modal');
    const confirm = document.getElementById('logout-confirm-btn');
    const cancel  = document.getElementById('logout-cancel-btn');
    if (!btn || !modal) return;

    btn.addEventListener('click', () => {
      modal.style.display = 'flex';
    });
    cancel.addEventListener('click', () => {
      modal.style.display = 'none';
    });
    modal.addEventListener('click', e => {
      if (e.target === modal) modal.style.display = 'none';
    });
    confirm.addEventListener('click', async () => {
      modal.style.display = 'none';
      const refresh = CLAP.Auth.getRefreshToken();
      if (refresh) {
        try { await CLAP.API.post('/auth/logout/', { refresh }); } catch {}
      }
      CLAP.Auth.clearTokens();
      CLAP.Toast.info('Logged out successfully.');
      setTimeout(() => { window.location.href = 'signin.html'; }, 600);
    });
  },

  _icons: {
    dashboard:   `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/></svg>`,
    assignments: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 10v6M2 10l10-5 10 5-10 5z"/><path d="M6 12v5c3 3 9 3 12 0v-5"/></svg>`,
    schedule:    `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>`,
    stress:      `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>`,
    settings:    `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>`,
    logout:      `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>`,
  },
};

window.AppShell = AppShell;