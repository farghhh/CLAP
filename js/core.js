/**
 * CLAP — Core Utilities
 * ============================================================
 * Provides: API layer (Django REST), auth helpers, form validation,
 * toast notifications, password tools, sidebar, and mini-calendar.
 * ============================================================
 */

'use strict';

const CONFIG = {
  BASE_URL:        'https://clap-production.up.railway.app/api',
  TOKEN_KEY:       'clap_access_token',
  REFRESH_KEY:     'clap_refresh_token',
  USER_KEY:        'clap_user',
  REQUEST_TIMEOUT: 10000,
};

const Auth = {
  setTokens(access, refresh) {
    localStorage.setItem(CONFIG.TOKEN_KEY, access);
    if (refresh) localStorage.setItem(CONFIG.REFRESH_KEY, refresh);
  },
  getAccessToken()  { return localStorage.getItem(CONFIG.TOKEN_KEY); },
  getRefreshToken() { return localStorage.getItem(CONFIG.REFRESH_KEY); },
  clearTokens() {
    localStorage.removeItem(CONFIG.TOKEN_KEY);
    localStorage.removeItem(CONFIG.REFRESH_KEY);
    localStorage.removeItem(CONFIG.USER_KEY);
  },
  setUser(user) { localStorage.setItem(CONFIG.USER_KEY, JSON.stringify(user)); },
  getUser() {
    try { return JSON.parse(localStorage.getItem(CONFIG.USER_KEY)); }
    catch { return null; }
  },
  isLoggedIn()  { return !!Auth.getAccessToken(); },
  requireAuth() {
    if (!Auth.isLoggedIn()) {
      window.location.href = 'signin.html';
      return false;
    }
    return true;
  },
  requireGuest() {
    if (Auth.isLoggedIn()) {
      window.location.href = 'dashboard.html';
      return false;
    }
    return true;
  },
};

class APIError extends Error {
  constructor(message, status, data = null) {
    super(message);
    this.name   = 'APIError';
    this.status = status;
    this.data   = data;
  }
}

const API = {
  async request(endpoint, { method = 'GET', body = null, auth = true, retry = true } = {}) {
    const url     = CONFIG.BASE_URL + endpoint;
    const headers = { 'Content-Type': 'application/json' };

    if (auth) {
      const token = Auth.getAccessToken();
      if (token) headers['Authorization'] = `Bearer ${token}`;
    }

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

      if (res.status === 401 && retry && auth) {
        const refreshed = await API.refreshToken();
        if (refreshed) return API.request(endpoint, { method, body, auth, retry: false });

        Auth.clearTokens();
        Toast.show('Session expired. Please sign in again.', 'warning');
        setTimeout(() => { window.location.href = 'signin.html'; }, 1500);
        return null;
      }

      if (res.status === 204 || res.headers.get('Content-Length') === '0') {
        if (!res.ok) throw new APIError('Request failed.', res.status, null);
        return null;
      }

      let data;
      const contentType = res.headers.get('Content-Type') || '';
      if (contentType.includes('application/json')) {
        data = await res.json();
      } else {
        const text = await res.text();
        data = text ? { detail: text } : null;
      }

      if (!res.ok) {
        const msg = API._extractErrorMsg(data);
        throw new APIError(msg, res.status, data);
      }

      return data;

    } catch (err) {
      clearTimeout(timeoutId);

      if (err.name === 'AbortError')  throw new APIError('Request timed out. Check your connection.', 0);
      if (err instanceof APIError)    throw err;
      if (!navigator.onLine)          throw new APIError('No internet connection.', 0);
      throw new APIError(err.message || 'Unexpected error.', 0);
    }
  },

  _extractErrorMsg(data) {
    if (!data)                    return 'Something went wrong.';
    if (typeof data === 'string') return data;
    if (data.detail)              return data.detail;
    if (data.non_field_errors)    return data.non_field_errors[0];
    if (data.error)               return data.error;

    const keys = Object.keys(data);
    if (keys.length) {
      const firstKey = keys[0];
      const msg = Array.isArray(data[firstKey]) ? data[firstKey][0] : data[firstKey];
      return `${firstKey}: ${msg}`;
    }
    return 'Something went wrong.';
  },

  async refreshToken() {
    if (API._refreshPromise) return API._refreshPromise;

    const refresh = Auth.getRefreshToken();
    if (!refresh) return false;

    API._refreshPromise = (async () => {
      try {
        const data = await API.request('/auth/token/refresh/', {
          method: 'POST',
          body:   { refresh },
          auth:   false,
          retry:  false,
        });
        Auth.setTokens(data.access, refresh);
        return true;
      } catch {
        return false;
      } finally {
        API._refreshPromise = null;
      }
    })();

    return API._refreshPromise;
  },

  _refreshPromise: null,

  get(endpoint, opts = {})         { return API.request(endpoint, { ...opts, method: 'GET' }); },
  post(endpoint, body, opts = {})  { return API.request(endpoint, { ...opts, method: 'POST',   body }); },
  put(endpoint, body, opts = {})   { return API.request(endpoint, { ...opts, method: 'PUT',    body }); },
  patch(endpoint, body, opts = {}) { return API.request(endpoint, { ...opts, method: 'PATCH',  body }); },
  'delete'(endpoint, opts = {})   { return API.request(endpoint, { ...opts, method: 'DELETE' }); },
};

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
  stressHistory: { Monday: 40, Tuesday: 55, Wednesday: 48, Thursday: 82, Friday: 60 },
};

const Toast = {
  _container: null,
  _icons: { success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️' },

  _init() {
    if (this._container) return;
    this._container = document.getElementById('toast-container');
    if (!this._container) {
      this._container = document.createElement('div');
      this._container.id = 'toast-container';
      document.body.appendChild(this._container);
    }
  },

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

    if (duration > 0) setTimeout(() => this._remove(toast), duration);
    return toast;
  },

  _remove(toast) {
    if (!toast || toast.classList.contains('hiding')) return;
    toast.classList.add('hiding');
    toast.addEventListener('animationend', () => toast.remove(), { once: true });
    setTimeout(() => toast.remove(), 400);
  },

  success(msg, d) { return this.show(msg, 'success', d); },
  error(msg, d)   { return this.show(msg, 'error',   d); },
  warning(msg, d) { return this.show(msg, 'warning', d); },
  info(msg, d)    { return this.show(msg, 'info',    d); },

  _escHtml(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
  },
};

const Validate = {
  rules: {
    required:    (v) => v.trim() !== '' || 'This field is required.',
    email:       (v) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v) || 'Enter a valid email address.',
    minLen:      (n) => (v) => v.length >= n || `Must be at least ${n} characters.`,
    maxLen:      (n) => (v) => v.length <= n || `Must be at most ${n} characters.`,
    pwMatch:     (ref) => (v) => v === ref.value || 'Passwords do not match.',
    /* FIX [m1]: Updated regex to include symbol requirement, matching the 4 UI pills
       (8+ chars, uppercase, number, symbol). Previously `Abcde123` passed but showed
       the Symbol pill as red, confusing users during the live demo. */
    pwStrength:  (v) => /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{8,}$/.test(v) ||
                        'Password must be 8+ chars with uppercase, lowercase, number and symbol.',
    noSpaces:    (v) => !/\s/.test(v) || 'Must not contain spaces.',
    positiveInt: (v) => (/^\d+$/.test(v) && parseInt(v) > 0) || 'Must be a positive number.',
    futureDate:  (v) => {
      if (!v) return 'This field is required.';
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      return new Date(v) >= today || 'Deadline must be today or in the future.';
    },
  },

  field(value, ruleFns) {
    for (const fn of ruleFns) {
      const result = fn(value);
      if (result !== true) return result;
    }
    return null;
  },

  setError(input, message) {
    const wrap  = input.closest('.form-group') || input.parentElement;
    const errEl = wrap ? wrap.querySelector('.field-error') : null;

    input.classList.toggle('error',   !!message);
    input.classList.toggle('success', !message && input.value.trim() !== '');
    input.setAttribute('aria-invalid', message ? 'true' : 'false');
    if (errEl) errEl.textContent = message || '';
  },

  form(fields) {
    let valid = true;
    for (const { input, rules } of fields) {
      const err = Validate.field(input.value, rules);
      Validate.setError(input, err);
      if (err) valid = false;
    }
    return valid;
  },

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

function initPasswordStrength(input, barEl, labelEl) {
  if (!input || !barEl || !labelEl) return;

  input.addEventListener('input', () => {
    const val = input.value;
    let score = 0;
    if (val.length >= 8)          score++;
    if (/[A-Z]/.test(val))        score++;
    if (/[a-z]/.test(val))        score++;
    if (/\d/.test(val))           score++;
    if (/[^A-Za-z0-9]/.test(val)) score++;

    const levels = ['', 'weak', 'fair', 'good', 'good', 'strong'];
    const labels = ['', 'Weak', 'Fair', 'Good', 'Good', 'Strong'];

    barEl.className     = `pw-strength-fill ${val ? (levels[score] || 'weak') : ''}`;
    labelEl.className   = `pw-strength-label ${val ? (levels[score] || 'weak') : ''}`;
    labelEl.textContent = val ? (labels[score] || 'Weak') : '';
  });
}

function initPwToggle(toggleBtn, inputEl) {
  if (!toggleBtn || !inputEl) return;

  toggleBtn.addEventListener('click', () => {
    const show = inputEl.type === 'password';
    inputEl.type = show ? 'text' : 'password';

    toggleBtn.innerHTML = show
      ? '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>'
      : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>';

    toggleBtn.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
  });
}

function hideLoader() {
  const loader = document.getElementById('page-loader');
  if (loader) {
    setTimeout(() => {
      loader.classList.add('fade-out');
      setTimeout(() => loader.remove(), 600);
    }, 300);
  }
}

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

  if (backdrop) backdrop.addEventListener('click', close);

  sidebar.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', () => {
      if (window.innerWidth <= 900) close();
    });
  });
}

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

window.addEventListener('offline', () => Toast.warning('You are offline. Some features may not work.'));
window.addEventListener('online',  () => Toast.success('Connection restored.'));

window.addEventListener('unhandledrejection', (event) => {
  const err = event.reason;
  if (err instanceof APIError) {
    Toast.error(err.message);
  } else {
    console.error('Unhandled error:', err);
  }
});

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