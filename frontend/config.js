/**
 * Where the API lives. This is the only thing the frontend needs to know about
 * the backend.
 *
 * Local development: the backend on port 8000.
 * Docker: rewritten at container start from WORDLE_API_BASE.
 */
window.WORDLE_CONFIG = {
  apiBase: 'http://localhost:8000',
};
