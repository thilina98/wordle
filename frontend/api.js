/**
 * The only file that knows the backend exists.
 *
 * Everything else in the frontend calls these functions and never touches
 * fetch. Requests are anonymous: there is no password, and signing in to an
 * account is not built into the page yet.
 */

'use strict';

const WordleApi = (() => {
  const base = (window.WORDLE_CONFIG && window.WORDLE_CONFIG.apiBase || '').replace(/\/$/, '');

  // Left behind by the shared-password version. The server no longer issues
  // these, and would refuse one if it were sent, so drop it.
  try {
    window.localStorage.removeItem('wordle.token');
  } catch {
    // No storage: nothing to clean up.
  }

  class ApiError extends Error {
    constructor(message, status) {
      super(message);
      this.status = status;
    }
  }

  async function request(path, { method = 'GET', body } = {}) {
    const headers = {};
    if (body !== undefined) headers['Content-Type'] = 'application/json';

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

    // Anything omitted falls back to the server's default: the ordinary
    // five-letter board with five attempts.
    createGame: ({ wordLength, maxAttempts } = {}) => {
      const body = {};
      if (wordLength !== undefined) body.word_length = wordLength;
      if (maxAttempts !== undefined) body.max_attempts = maxAttempts;
      return request('/api/games', {
        method: 'POST',
        body: Object.keys(body).length ? body : undefined,
      });
    },
    readGame: (id) => request(`/api/games/${encodeURIComponent(id)}`),

    /** Start the game's clock. Idempotent: only the server's first one counts. */
    startGame: (id) =>
      request(`/api/games/${encodeURIComponent(id)}/start`, { method: 'POST' }),

    submitGuess: (id, guess) =>
      request(`/api/games/${encodeURIComponent(id)}/guesses`, {
        method: 'POST',
        body: { guess },
      }),
  };
})();
