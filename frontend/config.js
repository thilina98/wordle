/**
 * Where the API and the sign-in provider are. The only settings the frontend has.
 *
 * Running from source: edit this file. Docker: replaced at container start
 * from frontend/.env (see docker-entrypoint.d-10-api-base.sh).
 *
 * auth: null turns sign-in off; everyone plays anonymously. To turn it on,
 * fill in all three values (backend/ACCOUNTS.md says where to find them):
 *
 *   auth: {
 *     issuer: 'https://dev-wordle.us.auth0.com/',   // same as the backend's
 *     clientId: 'aB3dE5fG7hI9jK1lM3nO5pQ7rS9tU1vW',  // the login app's Client ID
 *     audience: 'https://wordle-api',                // same as the backend's
 *   },
 */
window.WORDLE_CONFIG = {
  apiBase: 'http://localhost:8000',
  auth: null,
};
