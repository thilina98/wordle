/**
 * The only file that knows the backend exists.
 *
 * Everything else in the frontend calls these functions and never touches
 * fetch. A request carries the player's access token when they are signed in,
 * and nothing when they are not: anonymous play needs no account.
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

  /** Returns the access token to send, or null. Set by the page at startup. */
  let tokenFor = () => null;

  class ApiError extends Error {
    constructor(message, status) {
      super(message);
      this.status = status;
    }
  }

  async function request(path, { method = 'GET', body } = {}) {
    const headers = {};
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    const token = tokenFor();
    if (token) headers.Authorization = `Bearer ${token}`;

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
      const error = new ApiError(
        (payload && payload.detail) || `Request failed (${response.status})`,
        response.status,
      );
      // A 401 for a request that carried a token: the sign-in is no good.
      error.signInRejected = response.status === 401 && Boolean(token);
      throw error;
    }
    return payload;
  }

  return {
    ApiError,

    /** Where to get the access token from. Called before every request. */
    useToken(provider) {
      tokenFor = provider;
    },

    /** The signed-in player. The first call after signing up creates them. */
    readMyPlayer: () => request('/api/players/me'),

    /** Delete the signed-in player, their games and their provider account. */
    deleteMyPlayer: () => request('/api/players/me', { method: 'DELETE' }),

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
