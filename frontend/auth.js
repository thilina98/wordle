/**
 * Sign-in. The only file that knows an identity provider exists.
 *
 * Speaks standard OpenID Connect through oidc-client-ts, so any provider that
 * implements it (Auth0, Authentik, Keycloak...) works by changing config.js:
 * no provider is named in the code.
 *
 * The player signs in on the provider's own page and comes back here with a
 * one-time code, which is swapped for an access token (Authorization Code
 * flow with PKCE: no secret lives in the browser). The token is kept in
 * localStorage so a reload or a second tab stays signed in.
 *
 * Without auth settings in config.js, sign-in is off and `enabled` is false.
 */

'use strict';

const WordleAuth = (() => {
  const settings = window.WORDLE_CONFIG && window.WORDLE_CONFIG.auth;
  const enabled = Boolean(settings && settings.issuer && settings.clientId && settings.audience);

  // The page itself is where the provider sends the player back to.
  const home = `${window.location.origin}${window.location.pathname}`;

  let manager = null;
  let user = null;

  if (enabled) {
    const store = new oidc.WebStorageStateStore({ store: window.localStorage });
    manager = new oidc.UserManager({
      authority: settings.issuer,
      client_id: settings.clientId,
      redirect_uri: home,
      post_logout_redirect_uri: home,
      response_type: 'code',
      // openid: who they are. profile, email: a name to show and an email
      // the backend may use to join sign-in methods.
      scope: 'openid profile email',
      // Ask for an access token meant for our API, not just for sign-in.
      extraQueryParams: { audience: settings.audience },
      userStore: store,
      stateStore: store,
      // No background renewal: when the token expires, the player is asked
      // to sign in again.
      automaticSilentRenew: false,
      monitorSession: false,
    });
  }

  /** True when this page load is the provider sending the player back. */
  function isReturnFromProvider() {
    const query = new URLSearchParams(window.location.search);
    return query.has('state') && (query.has('code') || query.has('error'));
  }

  /** Drop the provider's code and state from the address bar. */
  function cleanAddressBar() {
    window.history.replaceState(null, '', home + window.location.hash);
  }

  return {
    enabled,

    /**
     * Load the stored sign-in, finishing it first if the provider just sent
     * the player back. Resolves to a message for the player when something
     * went wrong (cancelled, expired), or null.
     */
    async init() {
      if (!enabled) return null;
      let message = null;
      if (isReturnFromProvider()) {
        try {
          user = await manager.signinRedirectCallback();
        } catch (error) {
          message = error.error === 'access_denied' ? 'Sign-in cancelled.' : 'Sign-in failed. Try again.';
          console.error('Sign-in failed:', error);
        }
        cleanAddressBar();
      }
      if (!user) user = await manager.getUser();
      if (user && user.expired) {
        await manager.removeUser();
        user = null;
        message = message || 'Your sign-in expired. Sign in again.';
      }
      return message;
    },

    /** The access token to send to the API, or null when signed out. */
    accessToken() {
      return user && !user.expired ? user.access_token : null;
    },

    isSignedIn() {
      return Boolean(this.accessToken());
    },

    /** A name to show before the API has answered. */
    profileName() {
      return (user && user.profile && (user.profile.name || user.profile.nickname)) || '';
    },

    /** Leave for the provider's sign-in page. The player comes back to this page. */
    signIn() {
      return manager.signinRedirect();
    },

    /** Forget the sign-in here, and end the session at the provider too. */
    async signOut() {
      const idToken = user && user.id_token;
      await manager.removeUser();
      user = null;
      try {
        await manager.signoutRedirect({ id_token_hint: idToken });
      } catch (error) {
        // The provider publishes no sign-out address. The sign-in here is
        // gone; its own session may remain until it expires.
        console.warn('Provider sign-out unavailable:', error);
        window.location.replace(home);
      }
    },

    /** Forget the sign-in here only, e.g. after the API refused the token. */
    async forget() {
      user = null;
      if (enabled) await manager.removeUser();
    },
  };
})();
