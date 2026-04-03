/**
 * CLAP — Core Utilities
 * This file handles:
 * - API communication
 * - Authentication (login/logout)
 * - Data storage (localStorage)
 * - Toast notifications
 */

'use strict';

/* ============================================================
   CONFIG — Backend API settings
   ============================================================ */
const CONFIG = {
  BASE_URL: 'https://clap-production.up.railway.app/api', // your backend
  TOKEN_KEY: 'clap_access_token',
  REFRESH_KEY: 'clap_refresh_token',
  USER_KEY: 'clap_user',
  REQUEST_TIMEOUT: 10000, // 10 seconds timeout
};

/* ============================================================
   AUTH — Login / Session handling
   ============================================================ */
const Auth = {

  // Save tokens after login
  setTokens(access, refresh) {
    localStorage.setItem(CONFIG.TOKEN_KEY, access);
    if (refresh) localStorage.setItem(CONFIG.REFRESH_KEY, refresh);
  },

  // Get tokens
  getAccessToken()  { return localStorage.getItem(CONFIG.TOKEN_KEY); },
  getRefreshToken() { return localStorage.getItem(CONFIG.REFRESH_KEY); },

  // Remove all auth data (logout)
  clearTokens() {
    localStorage.removeItem(CONFIG.TOKEN_KEY);
    localStorage.removeItem(CONFIG.REFRESH_KEY);
    localStorage.removeItem(CONFIG.USER_KEY);
  },

  // Save user info
  setUser(user) {
    localStorage.setItem(CONFIG.USER_KEY, JSON.stringify(user));
  },

  // Get user info
  getUser() {
    try {
      return JSON.parse(localStorage.getItem(CONFIG.USER_KEY));
    } catch {
      return null;
    }
  },

  // Check login status
  isLoggedIn() {
    return !!Auth.getAccessToken();
  },

  // Protect page (must login)
  requireAuth() {
    if (!Auth.isLoggedIn()) {
      window.location.href = 'signin.html';
      return false;
    }
    return true;
  },

  // Prevent logged-in user from seeing auth pages
  requireGuest() {
    if (Auth.isLoggedIn()) {
      window.location.href = 'dashboard.html';
      return false;
    }
    return true;
  },
};

/* ============================================================
   API — Handles all backend requests
   ============================================================ */
const API = {

  async request(endpoint, { method = 'GET', body = null, auth = true, retry = true } = {}) {

    const url = CONFIG.BASE_URL + endpoint;
    const headers = { 'Content-Type': 'application/json' };

    // Add token if needed
    if (auth) {
      const token = Auth.getAccessToken();
      if (token) headers['Authorization'] = `Bearer ${token}`;
    }

    // Timeout control
    const controller = new AbortController();
    const timeoutId  = setTimeout(() => controller.abort(), CONFIG.REQUEST_TIMEOUT);

    try {
      const res = await fetch(url, {
        method,
        headers,
        body: body ? JSON.stringify(body) : null,
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      // 🔥 Token expired → try refresh
      if (res.status === 401 && retry) {
        const refreshed = await API.refreshToken();
        if (refreshed) {
          return API.request(endpoint, { method, body, auth, retry: false });
        }

        // Logout if refresh fails
        Auth.clearTokens();
        Toast.show('Session expired. Please sign in again.', 'warning');
        window.location.href = 'signin.html';
        return;
      }

      // Parse response
      let data;
      const contentType = res.headers.get('Content-Type') || '';

      if (contentType.includes('application/json')) {
        data = await res.json();
      } else {
        data = { detail: await res.text() };
      }

      // Handle error response
      if (!res.ok) {
        const msg = API._extractErrorMsg(data);
        throw new APIError(msg, res.status, data);
      }

      return data;

    } catch (err) {
      clearTimeout(timeoutId);

      if (err.name === 'AbortError') {
        throw new APIError('Request timeout.', 0);
      }

      if (!navigator.onLine) {
        throw new APIError('No internet connection.', 0);
      }

      throw err;
    }
  },

  // Extract readable error message
  _extractErrorMsg(data) {
    if (!data) return 'Something went wrong.';
    if (data.detail) return data.detail;

    const keys = Object.keys(data);
    if (keys.length) {
      const key = keys[0];
      return `${key}: ${data[key][0]}`;
    }

    return 'Error occurred.';
  },

  // Refresh token
  async refreshToken() {
    const refresh = Auth.getRefreshToken();
    if (!refresh) return false;

    try {
      const data = await API.request('/auth/token/refresh/', {
        method: 'POST',
        body: { refresh },
        auth: false,
        retry: false,
      });

      Auth.setTokens(data.access, refresh);
      return true;

    } catch {
      return false;
    }
  },

  // Shortcuts
  get(e, o={})    { return API.request(e, { ...o, method: 'GET' }); },
  post(e,b,o={})  { return API.request(e, { ...o, method: 'POST', body:b }); },
};

/* ============================================================
   DATA STORE — 🔥 VERY IMPORTANT (SYNC FIX)
   ============================================================ */
const DataStore = {

  // Get assignments (shared by ALL pages)
  getAssignments() {
    return JSON.parse(localStorage.getItem('clap_assignments')) || [];
  },

  // Save assignments
  saveAssignments(list) {
    localStorage.setItem('clap_assignments', JSON.stringify(list));
  },

  // Get schedule
  getSchedule() {
    return JSON.parse(localStorage.getItem('clap_schedule')) || {};
  },

  // Save schedule
  saveSchedule(data) {
    localStorage.setItem('clap_schedule', JSON.stringify(data));
  }
};

/* ============================================================
   🔥 SCHEDULE GENERATOR (IMPORTANT FIX)
   ============================================================ */
function generateSchedule() {
  const assignments = DataStore.getAssignments();

  const schedule = {
    Monday: [], Tuesday: [], Wednesday: [],
    Thursday: [], Friday: [], Saturday: [], Sunday: []
  };

  const days = Object.keys(schedule);
  let i = 0;

  assignments.forEach(a => {
    schedule[days[i]].push({
      title: a.title,
      time: "10:00",
      difficulty: a.difficulty
    });

    i = (i + 1) % 7;
  });

  DataStore.saveSchedule(schedule);
}

/* ============================================================
   TOAST — Notification popup
   ============================================================ */
const Toast = {

  show(msg, type='info') {
    alert(`${type.toUpperCase()}: ${msg}`); // simple version
  },

  success(msg){ this.show(msg,'success'); },
  error(msg){ this.show(msg,'error'); }
};