/**
 * The account corner of the header: sign-in button, player menu, and the
 * delete-account confirmation.
 *
 * Every page has an empty `<nav id="account">`; this module builds what goes
 * in it, so the menu is written once and looks the same everywhere. The page
 * says which one it is, and the menu links to the other.
 */

import { api } from './api.js';
import { auth } from './auth.js';
import { forgetSavedGame } from './saved-game.js';
import { toast } from './toast.js';

/** The menu's first item: a link to the page you are not on. */
const OTHER_PAGE = {
  game: { href: 'stats.html', label: 'Statistics' },
  stats: { href: './', label: 'Play' },
};

const MENU = (link) => `
  <button class="bar-button" type="button" data-sign-in hidden>Sign in</button>
  <div class="player" data-player hidden>
    <button class="bar-button" type="button" data-player-button
            aria-haspopup="menu" aria-expanded="false" aria-controls="player-menu">
      <span class="player-name" data-player-name></span>
      <span class="caret" aria-hidden="true">&#9662;</span>
    </button>
    <div id="player-menu" class="menu" role="menu" hidden>
      <a href="${link.href}" role="menuitem">${link.label}</a>
      <button type="button" role="menuitem" data-sign-out>Sign out</button>
      <div class="menu-separator" role="separator"></div>
      <button class="menu-danger" type="button" role="menuitem" data-delete>Delete account</button>
    </div>
  </div>`;

const CONFIRM_DELETE = `
  <div class="card card-centred" role="alertdialog" aria-modal="true"
       aria-labelledby="delete-title" aria-describedby="delete-text">
    <h2 id="delete-title">Delete account?</h2>
    <p id="delete-text">Your player, your games and your sign-in are removed for good.
      You can sign up again later, starting from nothing.</p>
    <div class="actions">
      <button class="secondary" type="button" data-cancel>Cancel</button>
      <button class="danger" type="button" data-confirm>Delete</button>
    </div>
  </div>`;

/**
 * Build the account corner for `page` ('game' or 'stats').
 *
 * Nothing is known about the player until `start()` resolves. Returns:
 *   start()             sign in from storage (or the provider's return), load the player
 *   isOpen()            the menu or the confirmation has the keyboard
 *   signInLost(reason)  the API refused the sign-in: forget it, carry on signed out
 */
export function createAccount({ page }) {
  const nav = document.getElementById('account');
  nav.innerHTML = MENU(OTHER_PAGE[page]);
  const confirm = document.createElement('div');
  confirm.className = 'result';
  confirm.hidden = true;
  confirm.innerHTML = CONFIRM_DELETE;
  document.body.append(confirm);

  const find = (root, name) => root.querySelector(`[data-${name}]`);
  const signInButton = find(nav, 'sign-in');
  const playerBox = find(nav, 'player');
  const playerButton = find(nav, 'player-button');
  const playerName = find(nav, 'player-name');
  const menu = nav.querySelector('[role="menu"]');
  const cancel = find(confirm, 'cancel');
  const confirmDelete = find(confirm, 'confirm');

  /** The signed-in player as the API knows them, or null. */
  let player = null;

  const menuOpen = () => !menu.hidden;
  const confirmOpen = () => !confirm.hidden;

  function openMenu() {
    menu.hidden = false;
    playerButton.setAttribute('aria-expanded', 'true');
    menu.querySelector('[role="menuitem"]').focus();
  }

  function closeMenu() {
    menu.hidden = true;
    playerButton.setAttribute('aria-expanded', 'false');
  }

  function paint() {
    nav.hidden = !auth.enabled;
    if (!auth.enabled) return;
    const signedIn = auth.isSignedIn();
    signInButton.hidden = signedIn;
    playerBox.hidden = !signedIn;
    playerName.textContent = (player && player.display_name) || auth.profileName() || 'Signed in';
    if (!signedIn) closeMenu();
  }

  async function signInLost(reason) {
    await auth.forget();
    player = null;
    paint();
    toast(
      reason === 'This account was deleted'
        ? 'This account was deleted.'
        : 'Your sign-in expired. Sign in again.',
      'error',
    );
  }

  /** Ask the API who is signed in. The first call after signing up creates the player. */
  async function loadPlayer() {
    player = null;
    if (auth.isSignedIn()) {
      try {
        player = await api.readMyPlayer();
      } catch (error) {
        if (error.signInRejected) await signInLost(error.message);
        else toast('Could not load your account. You can keep playing.', 'error');
      }
    }
    paint();
  }

  signInButton.addEventListener('click', () => {
    auth.signIn().catch((error) => {
      console.error(error);
      toast('Could not reach the sign-in page. Try again.', 'error');
    });
  });

  playerButton.addEventListener('click', () => (menuOpen() ? closeMenu() : openMenu()));

  find(nav, 'sign-out').addEventListener('click', () => {
    closeMenu();
    auth.signOut();
  });

  find(nav, 'delete').addEventListener('click', () => {
    closeMenu();
    confirm.hidden = false;
    cancel.focus();
  });

  cancel.addEventListener('click', () => {
    confirm.hidden = true;
    playerButton.focus();
  });

  confirmDelete.addEventListener('click', async () => {
    confirmDelete.disabled = cancel.disabled = true;
    confirmDelete.textContent = 'Deleting…';
    try {
      await api.deleteMyPlayer();
      // The current game belonged to the account and is gone with it.
      forgetSavedGame();
      await auth.signOut();   // leaves for the provider, then comes back signed out
    } catch (error) {
      confirm.hidden = true;
      if (error.signInRejected) await signInLost(error.message);
      else toast('Could not delete your account. Nothing was removed. Try again.', 'error');
    } finally {
      confirmDelete.disabled = cancel.disabled = false;
      confirmDelete.textContent = 'Delete';
    }
  });

  // Clicking anywhere else closes the menu.
  document.addEventListener('click', (event) => {
    if (menuOpen() && !playerBox.contains(event.target)) closeMenu();
  });

  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    if (confirmOpen()) cancel.click();
    else if (menuOpen()) {
      closeMenu();
      playerButton.focus();
    }
  });

  return {
    async start() {
      let message = null;
      try {
        message = await auth.init();   // also finishes a sign-in in progress
      } catch (error) {
        console.error(error);
        message = 'Sign-in is unavailable right now. You can keep playing.';
      }
      paint();
      if (message) toast(message, 'error');
      await loadPlayer();
    },
    isOpen: () => menuOpen() || confirmOpen(),
    signInLost,
  };
}
