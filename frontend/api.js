/**
 * The only file that knows the backend exists.
 *
 * Holds the access token and puts it on every request. Everything else in the
 * frontend calls these functions and never touches fetch or the token.
 */

'use strict';

const WordleApi = (() => {
  const TOKEN_KEY = 'wordle.token';
  const base = (window.WORDLE_CONFIG && window.WORDLE_CONFIG.apiBase || '').replace(/\/$/, '');

  /** Storage is unavailable in some private-browsing modes; degrade, do not crash. */
  const store = {
    read() {
      try {
        return window.localStorage.getItem(TOKEN_KEY);
      } catch {
        return null;
      }
    },
    write(value) {
      try {
        if (value === null) window.localStorage.removeItem(TOKEN_KEY);
        else window.localStorage.setItem(TOKEN_KEY, value);
      } catch {
        // Session lasts until reload. Playable, just not resumable.
      }
    },
  };

  let token = store.read();

  class ApiError extends Error {
    constructor(message, status) {
      super(message);
      this.status = status;
    }
  }

  async function request(path, { method = 'GET', body, auth = true } = {}) {
    const headers = {};
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (auth && token) headers.Authorization = `Bearer ${token}`;

    let response;
    try {
      response = await fetch(`${base}${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (cause) {
      // A CORS rejection and a dead backend look identical from here.
      throw new ApiError('Cannot reach the server', 0);
    }

    const payload = response.status === 204 ? null : await response.json().catch(() => null);
    if (!response.ok) {
      throw new ApiError(
        (payload && payload.detail) || `Request failed (${response.status})`,
        response.status,
      );
    }
    return payload;
  }

  return {
    ApiError,

    hasToken: () => Boolean(token),

    async login(password) {
      const { token: issued } = await request('/api/login', {
        method: 'POST',
        body: { password },
        auth: false,
      });
      token = issued;
      store.write(token);
    },

    logout() {
      token = null;
      store.write(null);
    },

    /** True if the stored token is still good. Cheap enough to call on load. */
    async sessionIsValid() {
      if (!token) return false;
      try {
        await request('/api/session');
        return true;
      } catch (error) {
        if (error.status === 401) return false;
        throw error;
      }
    },

    createGame: () => request('/api/games', { method: 'POST' }),
    readGame: (id) => request(`/api/games/${encodeURIComponent(id)}`),
    submitGuess: (id, guess) =>
      request(`/api/games/${encodeURIComponent(id)}/guesses`, {
        method: 'POST',
        body: { guess },
      }),
  };
})();
