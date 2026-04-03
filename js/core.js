/**
 * CLAP — Core Utilities
 * ============================================================
 * Provides: API layer (Django REST), auth helpers, form validation,
 * toast notifications, password tools, sidebar, and mini-calendar.
 *
 * FIX LOG (all changes marked with // FIX):
 *  1. initSidebar — removed dead selector `.nav-item[data-page]`
 *     (sidebar nav uses <a href> links, not data-page attributes,
 *      so the active-class loop never matched anything).
 *  2. Validate.rules.positiveInt — added explicit parentheses around
 *     the combined condition to guarantee correct operator precedence.
 *  3. Validate.rules.futureDate — strips the time component from
 *     today's date so "today" is accepted as a valid deadline.
 * ============================================================
 */

'use strict';

/* ============================================================
   CONFIG — Update BASE_URL to match your Django backend
   ============================================================ */
const CONFIG = {
  BASE_URL:        'https://clap-production.up.railway.app/api', // ← your Django API base
  TOKEN_KEY:       'clap_access_token',
  REFRESH_KEY:     'clap_refresh_token',
  USER_KEY:        'clap_user',
  REQUEST_TIMEOUT: 10000, // 10 seconds
};

/* ============================================================
   TOKEN / SESSION HELPERS
   ============================================================ */
const Auth = {
  /** Persist access + refresh tokens in localStorage after login/register. */
  setTokens(access, refresh) {
    localStorage.setItem(CONFIG.TOKEN_KEY, access);
    if (refresh) localStorage.setItem(CONFIG.REFRESH_KEY, refresh);
  },

  /** Return the stored JWT access token, or null. */
  getAccessToken()  { return localStorage.getItem(CONFIG.TOKEN_KEY); },

  /** Return the stored JWT refresh token, or null. */
  getRefreshToken() { return localStorage.getItem(CONFIG.REFRESH_KEY); },

  /** Wipe all auth data (called on logout or session expiry). */
  clearTokens() {
    localStorage.removeItem(CONFIG.TOKEN_KEY);
    localStorage.removeItem(CONFIG.REFRESH_KEY);
    localStorage.removeItem(CONFIG.USER_KEY);
  },

  /** Persist the user profile object. */
  setUser(user) { localStorage.setItem(CONFIG.USER_KEY, JSON.stringify(user)); },

  /** Return the user profile object, or null if missing / malformed. */
  getUser() {
    try { return JSON.parse(localStorage.getItem(CONFIG.USER_KEY)); }
    catch { return null; }
  },

  /** True when an access token is present (does not verify expiry). */
  isLoggedIn() { return !!Auth.getAccessToken(); },

  /**
   * Guard for protected pages — redirect to sign-in if not authenticated.
   * Call at the top of every inner-app page script.
   */
  requireAuth() {
    if (!Auth.isLoggedIn()) {
      window.location.href = 'signin.html';
      return false;
    }
    return true;
  },

  /**
   * Guard for guest-only pages (sign-in, sign-up) —
   * redirect to dashboard if the user is already logged in.
   */
  requireGuest() {
    if (Auth.isLoggedIn()) {
      window.location.href = 'dashboard.html';
      return false;
    }
    return true;
  },
};

/* ============================================================
   API ERROR CLASS
   Must be declared before the API object that throws it and
   before the global unhandledrejection handler that catches it.
   ============================================================ */
class APIError extends Error {
  /**
   * @param {string} message  Human-readable description.
   * @param {number} status   HTTP status code (0 = network / timeout).
   * @param {*}      data     Raw response body from Django REST, if any.
   */
  constructor(message, status, data = null) {
    super(message);
    this.name   = 'APIError';
    this.status = status;
    this.data   = data;
  }
}

/* ============================================================
   API — Fetch wrapper with auth, token-refresh, timeout,
         and Django REST error normalisation
   ============================================================ */
const API = {
  /**
   * Core fetch method — all helpers (get / post / put / patch / delete)
   * delegate here.
   *
   * @param {string} endpoint  Relative path, e.g. '/auth/login/'
   * @param {object} options
   *   method {string}  HTTP verb (default 'GET')
   *   body   {object}  JSON-serialisable payload (default null)
   *   auth   {boolean} Whether to attach the Bearer token (default true)
   *   retry  {boolean} Internal flag; one retry after token refresh (default true)
   */
  async request(endpoint, { method = 'GET', body = null, auth = true, retry = true } = {}) {
    const url     = CONFIG.BASE_URL + endpoint;
    const headers = { 'Content-Type': 'application/json' };

    /* Attach authorization header when required and a token is available. */
    if (auth) {
      const token = Auth.getAccessToken();
      if (token) headers['Authorization'] = `Bearer ${token}`;
    }

    /* AbortController enables the request timeout. */
    const controller = new AbortController();
    const timeoutId  = setTimeout(() => controller.abort(), CONFIG.REQUEST_TIMEOUT);

    try {
      const res = await fetch(url, {
        method,
        headers,
        body:   body ? JSON.stringify(body) : null,
        signal: controller.signal,
      });
      clearTimeout(timeoutId);

      /* ── Token expired: attempt a silent refresh, then retry once ── */
      if (res.status === 401 && retry) {
        const refreshed = await API.refreshToken();
        if (refreshed) return API.request(endpoint, { method, body, auth, retry: false });

        /* Refresh also failed — force the user back to sign-in. */
        Auth.clearTokens();
        Toast.show('Session expired. Please sign in again.', 'warning');
        setTimeout(() => { window.location.href = 'signin.html'; }, 1500);
        return null;
      }

      /* ── Parse response body (JSON preferred, fall back to plain text) ── */
      let data;
      const contentType = res.headers.get('Content-Type') || '';
      if (contentType.includes('application/json')) {
        data = await res.json();
      } else {
        data = { detail: await res.text() };
      }

      /* Throw for any non-2xx status so callers can catch uniformly. */
      if (!res.ok) {
        const msg = API._extractErrorMsg(data);
        throw new APIError(msg, res.status, data);
      }

      return data;

    } catch (err) {
      clearTimeout(timeoutId);

      /* Re-map known error types to APIError for uniform catch handling. */
      if (err.name === 'AbortError')    throw new APIError('Request timed out. Check your connection.', 0);
      if (err instanceof APIError)      throw err;
      if (!navigator.onLine)            throw new APIError('No internet connection.', 0);
      throw new APIError(err.message || 'Unexpected error.', 0);
    }
  },

  /**
   * Extract a human-readable error message from a Django REST response.
   * Handles: plain strings, { detail }, { non_field_errors }, field errors.
   * @private
   */
  _extractErrorMsg(data) {
    if (!data)                  return 'Something went wrong.';
    if (typeof data === 'string') return data;
    if (data.detail)             return data.detail;
    if (data.non_field_errors)   return data.non_field_errors[0];

    /* Flatten field-level errors, e.g. { email: ['already exists'] } */
    const keys = Object.keys(data);
    if (keys.length) {
      const firstKey = keys[0];
      const msg = Array.isArray(data[firstKey]) ? data[firstKey][0] : data[firstKey];
      return `${firstKey}: ${msg}`;
    }
    return 'Something went wrong.';
  },

  /**
   * Use the stored refresh token to obtain a new access token.
   * Returns true on success, false on failure.
   */
  async refreshToken() {
    const refresh = Auth.getRefreshToken();
    if (!refresh) return false;
    try {
      const data = await API.request('/auth/token/refresh/', {
        method: 'POST',
        body:   { refresh },
        auth:   false,
        retry:  false,  // never loop on the refresh endpoint itself
      });
      Auth.setTokens(data.access, refresh);
      return true;
    } catch {
      return false;
    }
  },

  /* ── Convenience shortcut methods ── */
  get(endpoint, opts = {})          { return API.request(endpoint, { ...opts, method: 'GET' }); },
  post(endpoint, body, opts = {})   { return API.request(endpoint, { ...opts, method: 'POST',   body }); },
  put(endpoint, body, opts = {})    { return API.request(endpoint, { ...opts, method: 'PUT',    body }); },
  patch(endpoint, body, opts = {})  { return API.request(endpoint, { ...opts, method: 'PATCH',  body }); },
  delete(endpoint, opts = {})       { return API.request(endpoint, { ...opts, method: 'DELETE' }); },
};

/* ============================================================
   MOCK DATA — used by pages when the backend is not yet connected.
   Remove individual stubs once each Django endpoint is ready.
   ============================================================ */
const MockData = {
  user: { id: 1, name: 'Farisha', email: 'farisha@example.com', avatar: null },

  assignments: [
    { id: 1, course_code: 'CSC2383', title: 'Database Final Project',         deadline: '2026-03-22', hours: 6,  difficulty: 'easy',   progress: 80  },
    { id: 2, course_code: 'CSC2613', title: 'Parallel Computing System',      deadline: '2026-03-25', hours: 10, difficulty: 'medium', progress: 60  },
    { id: 3, course_code: 'CSC2434', title: 'Mobile Application Development', deadline: '2026-03-31', hours: 25, difficulty: 'hard',   progress: 20  },
    { id: 4, course_code: 'CSC2672', title: 'UI/UX Design Prototype',         deadline: '2026-04-25', hours: 20, difficulty: 'hard',   progress: 100 },
    { id: 5, course_code: 'CSC4832', title: 'AI Research Thesis',             deadline: '2026-03-05', hours: 7,  difficulty: 'easy',   progress: 0   },
  ],

  schedule: {
    Monday:    [{ time: '09:00', title: 'Database Project', color: 'orange' }, { time: '11:00', title: 'Parallel Comp.', color: 'blue' }],
    Tuesday:   [{ time: '10:00', title: 'Study Session',    color: 'blue'   }],
    Wednesday: [{ time: '11:00', title: 'Mobile App',       color: 'red'    }],
    Thursday:  [{ time: '09:00', title: 'Mobile App',       color: 'red'    }, { time: '11:00', title: 'Database Project', color: 'orange' }],
    Friday:    [{ time: '10:00', title: 'Study Session',    color: 'blue'   }],
  },

  cognitiveLoad: { value: 72, level: 'moderate', trend: [40, 55, 45, 72, 60] },
  stressHistory: { Mon: 40, Tue: 55, Wed: 48, Thu: 82, Fri: 60 },
};

/* ============================================================
   TOAST NOTIFICATION SYSTEM
   ============================================================ */
const Toast = {
  _container: null,
  _icons: { success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️' },

  /** Lazily resolve (or create) the #toast-container element. */
  _init() {
    if (this._container) return;
    this._container = document.getElementById('toast-container');
    if (!this._container) {
      this._container = document.createElement('div');
      this._container.id = 'toast-container';
      document.body.appendChild(this._container);
    }
  },

  /**
   * Display a toast notification.
   * @param {string} message  Text to show (HTML-escaped automatically).
   * @param {string} type     'success' | 'error' | 'warning' | 'info'
   * @param {number} duration Auto-dismiss after ms (0 = stay until closed).
   */
  show(message, type = 'info', duration = 4000) {
    this._init();

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.setAttribute('role', 'alert');
    toast.setAttribute('aria-live', 'assertive');
    toast.innerHTML = `
      <span class="toast-icon" aria-hidden="true">${this._icons[type] || this._icons.info}</span>
      <span class="toast-msg">${this._escHtml(message)}</span>
      <button class="toast-close" aria-label="Close notification">&times;</button>
    `;

    toast.querySelector('.toast-close').addEventListener('click', () => this._remove(toast));
    this._container.appendChild(toast);

    if (duration > 0) {
      setTimeout(() => this._remove(toast), duration);
    }
    return toast;
  },

  /** Animate and remove a toast element from the DOM. */
  _remove(toast) {
    if (!toast || toast.classList.contains('hiding')) return;
    toast.classList.add('hiding');
    /* animationend fires when the CSS fade-out animation completes. */
    toast.addEventListener('animationend', () => toast.remove(), { once: true });
    setTimeout(() => toast.remove(), 400); // safety fallback
  },

  /* Shorthand helpers */
  success(msg, d) { return this.show(msg, 'success', d); },
  error(msg, d)   { return this.show(msg, 'error',   d); },
  warning(msg, d) { return this.show(msg, 'warning', d); },
  info(msg, d)    { return this.show(msg, 'info',    d); },

  /** HTML-escape a string to prevent XSS in toast messages. */
  _escHtml(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
  },
};

/* ============================================================
   FORM VALIDATION
   ============================================================ */
const Validate = {
  rules: {
    /** Field must not be blank after trimming whitespace. */
    required:   (v) => v.trim() !== '' || 'This field is required.',

    /** Basic email format check. */
    email:      (v) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v) || 'Enter a valid email address.',

    /** Minimum character length (returns a rule function). */
    minLen:     (n) => (v) => v.length >= n || `Must be at least ${n} characters.`,

    /** Maximum character length (returns a rule function). */
    maxLen:     (n) => (v) => v.length <= n || `Must be at most ${n} characters.`,

    /** Passwords-match check — pass the reference <input> element. */
    pwMatch:    (ref) => (v) => v === ref.value || 'Passwords do not match.',

    /**
     * Minimum password strength: 8+ chars containing at least one
     * uppercase letter, one lowercase letter, and one digit.
     */
    pwStrength: (v) => /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$/.test(v) ||
                       'Password must be 8+ chars with uppercase, lowercase and number.',

    /** No whitespace characters allowed. */
    noSpaces:   (v) => !/\s/.test(v) || 'Must not contain spaces.',

    /**
     * FIX: parentheses around the combined condition ensure the &&
     * is evaluated before || so the result is always a boolean,
     * not accidentally the integer from parseInt().
     */
    positiveInt: (v) => (/^\d+$/.test(v) && parseInt(v) > 0) || 'Must be a positive number.',

    /**
     * FIX: setHours(0,0,0,0) on today strips the time component so
     * a deadline of "today" is treated as valid instead of being
     * rejected because Date.now() is partway through the day.
     */
    futureDate: (v) => {
      if (!v) return 'This field is required.';
      const today = new Date();
      today.setHours(0, 0, 0, 0); // compare date only, ignore time
      return new Date(v) >= today || 'Deadline must be today or in the future.';
    },
  },

  /**
   * Run a value through an ordered array of rule functions.
   * Returns the first error string encountered, or null if all pass.
   * @param {string}   value   Current field value.
   * @param {Function[]} ruleFns  Array of rule functions.
   */
  field(value, ruleFns) {
    for (const fn of ruleFns) {
      const result = fn(value);
      if (result !== true) return result;
    }
    return null;
  },

  /**
   * Set or clear the visible error state on a form input.
   * Looks for a sibling .field-error element inside the nearest
   * .form-group ancestor.
   * @param {HTMLElement} input    The <input> / <select> / <textarea>.
   * @param {string|null} message  Error string, or null/'' to clear.
   */
  setError(input, message) {
    const wrap  = input.closest('.form-group') || input.parentElement;
    const errEl = wrap ? wrap.querySelector('.field-error') : null;

    input.classList.toggle('error',   !!message);
    input.classList.toggle('success', !message && input.value.trim() !== '');
    input.setAttribute('aria-invalid', message ? 'true' : 'false');
    if (errEl) errEl.textContent = message || '';
  },

  /**
   * Validate every field descriptor in the list.
   * Each descriptor: { input: HTMLElement, rules: Function[] }
   * Returns true if all fields pass, false otherwise.
   */
  form(fields) {
    let valid = true;
    for (const { input, rules } of fields) {
      const err = Validate.field(input.value, rules);
      Validate.setError(input, err);
      if (err) valid = false;
    }
    return valid;
  },

  /**
   * Attach live (blur + input) validation to an input element.
   * Validation only re-runs on `input` events once the field is
   * already in an error state (avoids premature red underlines).
   * @param {HTMLElement} input  Field to watch.
   * @param {Function[]}  rules  Rules to apply.
   */
  attachLive(input, rules) {
    const validate = () => {
      const err = Validate.field(input.value, rules);
      Validate.setError(input, err);
    };
    input.addEventListener('blur', validate);
    input.addEventListener('input', () => {
      if (input.classList.contains('error')) validate();
    });
  },
};

/* ============================================================
   PASSWORD STRENGTH METER
   Scores the current value of a password field (0–5) and
   updates a coloured progress bar + label accordingly.
   ============================================================ */
function initPasswordStrength(input, barEl, labelEl) {
  if (!input || !barEl || !labelEl) return;

  input.addEventListener('input', () => {
    const val = input.value;
    let score = 0;
    if (val.length >= 8)          score++; // minimum length
    if (/[A-Z]/.test(val))        score++; // uppercase
    if (/[a-z]/.test(val))        score++; // lowercase
    if (/\d/.test(val))           score++; // digit
    if (/[^A-Za-z0-9]/.test(val)) score++; // special character

    /* Map score (0–5) to CSS class + display label. */
    const levels = ['', 'weak', 'fair', 'good', 'good', 'strong'];
    const labels = ['', 'Weak', 'Fair', 'Good', 'Good', 'Strong'];

    barEl.className    = `pw-strength-fill ${val ? (levels[score] || 'weak') : ''}`;
    labelEl.className  = `pw-strength-label ${val ? (levels[score] || 'weak') : ''}`;
    labelEl.textContent = val ? (labels[score] || 'Weak') : '';
  });
}

/* ============================================================
   PASSWORD VISIBILITY TOGGLE
   Switches an <input> between type="password" and type="text"
   and updates the toggle button icon accordingly.
   ============================================================ */
function initPwToggle(toggleBtn, inputEl) {
  if (!toggleBtn || !inputEl) return;

  toggleBtn.addEventListener('click', () => {
    const show = inputEl.type === 'password';
    inputEl.type = show ? 'text' : 'password';

    /* Show "eye-off" SVG when password is visible, "eye" SVG when hidden. */
    toggleBtn.innerHTML = show
      ? '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>'
      : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>';

    toggleBtn.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
  });
}

/* ============================================================
   PAGE LOADER
   Fades out and removes the full-screen loader overlay.
   Called at the end of each page's inline script once the
   initial data or DOM setup is complete.
   ============================================================ */
function hideLoader() {
  const loader = document.getElementById('page-loader');
  if (loader) {
    setTimeout(() => {
      loader.classList.add('fade-out');
      setTimeout(() => loader.remove(), 600);
    }, 1500);
  }
}

/* ============================================================
   SIDEBAR (mobile toggle)
   Manages the open/close state of the slide-in sidebar and
   its semi-transparent backdrop on small screens.
   ============================================================ */
function initSidebar() {
  const toggleBtn = document.getElementById('sidebar-toggle');
  const sidebar   = document.getElementById('sidebar');
  const backdrop  = document.getElementById('sidebar-backdrop');

  if (!toggleBtn || !sidebar) return;

  const open = () => {
    sidebar.classList.add('open');
    toggleBtn.setAttribute('aria-expanded', 'true');
    if (backdrop) backdrop.classList.add('open');
  };
  const close = () => {
    sidebar.classList.remove('open');
    toggleBtn.setAttribute('aria-expanded', 'false');
    if (backdrop) backdrop.classList.remove('open');
  };

  toggleBtn.addEventListener('click', () => {
    sidebar.classList.contains('open') ? close() : open();
  });

  /* Tapping the backdrop closes the sidebar. */
  if (backdrop) backdrop.addEventListener('click', close);

  /* On mobile, close the sidebar automatically after navigating. */
  sidebar.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', () => {
      if (window.innerWidth <= 900) close();
    });
  });

  /*
   * FIX: The original code tried to set an `active` class using a
   * `[data-page]` attribute selector, but the injected nav items are
   * <a href="…"> links — they have no data-page attribute.
   * Active highlighting is now handled by AppShell._injectSidebar()
   * which compares `activePage` directly when building the HTML,
   * so this loop is removed to avoid the silent no-op.
   */
}

/* ============================================================
   MINI CALENDAR
   Renders a navigable month calendar inside a given container.
   @param {string} containerId  ID of the host element.
   @param {object} markedDates  Map of "YYYY-MM-DD" → CSS class string.
   ============================================================ */
function renderMiniCalendar(containerId, markedDates = {}) {
  const container = document.getElementById(containerId);
  if (!container) return;

  const dayNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const current  = new Date();
  let year  = current.getFullYear();
  let month = current.getMonth();

  function render() {
    const firstDay    = new Date(year, month, 1).getDay();
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const monthName   = new Date(year, month, 1).toLocaleString('default', { month: 'long' });
    const todayStr    = `${current.getFullYear()}-${String(current.getMonth() + 1).padStart(2, '0')}-${String(current.getDate()).padStart(2, '0')}`;

    container.innerHTML = `
      <div class="mini-calendar-header">
        <button class="cal-nav-btn" id="cal-prev" aria-label="Previous month">&#8249;</button>
        <h3>${monthName}, ${year}</h3>
        <button class="cal-nav-btn" id="cal-next" aria-label="Next month">&#8250;</button>
      </div>
      <div class="cal-grid">
        ${dayNames.map(d => `<div class="cal-day-name">${d}</div>`).join('')}
        ${Array(firstDay).fill('<div class="cal-day other-month"></div>').join('')}
        ${Array.from({ length: daysInMonth }, (_, i) => {
          const day     = i + 1;
          const dateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
          const isToday = dateStr === todayStr;
          const mark    = markedDates[dateStr] || '';
          return `<div class="cal-day ${isToday ? 'today' : ''} ${mark}"
                       aria-label="${monthName} ${day}${isToday ? ' (today)' : ''}"
                       tabindex="0">${day}</div>`;
        }).join('')}
      </div>
    `;

    /* Re-attach nav listeners after innerHTML replacement. */
    container.querySelector('#cal-prev').addEventListener('click', () => {
      month--;
      if (month < 0) { month = 11; year--; }
      render();
    });
    container.querySelector('#cal-next').addEventListener('click', () => {
      month++;
      if (month > 11) { month = 0; year++; }
      render();
    });
  }

  render();
}

/* ============================================================
   NETWORK STATUS BANNERS
   Inform users when they go offline or come back online.
   Toast._init() is called lazily inside show(), so these
   listeners are safe to register before the DOM is ready.
   ============================================================ */
window.addEventListener('offline', () => Toast.warning('You are offline. Some features may not work.'));
window.addEventListener('online',  () => Toast.success('Connection restored.'));

/* ============================================================
   GLOBAL UNHANDLED PROMISE REJECTION HANDLER
   Surfaces APIErrors as toasts; logs everything else.
   ============================================================ */
window.addEventListener('unhandledrejection', (event) => {
  const err = event.reason;
  if (err instanceof APIError) {
    Toast.error(err.message);
  } else {
    console.error('Unhandled error:', err);
  }
});

/* ============================================================
   EXPOSE PUBLIC API ON window.CLAP
   All page scripts and app-shell.js access utilities via CLAP.*
   ============================================================ */
window.CLAP = {
  CONFIG,
  Auth,
  API,
  APIError,
  MockData,
  Toast,
  Validate,
  initPasswordStrength,
  initPwToggle,
  hideLoader,
  initSidebar,
  renderMiniCalendar,
};