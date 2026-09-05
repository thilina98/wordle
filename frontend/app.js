/**
 * Wordle — view layer.
 *
 * Holds no game rules and no knowledge of HTTP. The server decides which words
 * are valid and what colour each letter gets; WordleApi does the talking. This
 * file draws the board and collects key presses.
 */

'use strict';

const STORAGE_KEY = 'wordle.gameId';
const REVEAL_STEP = 220;   // gap between tiles flipping, ms
const REVEAL_TURN = 240;   // point in the flip where the colour appears, ms
const KEY_ROWS = [
  ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p'],
  ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l'],
  ['Enter', 'z', 'x', 'c', 'v', 'b', 'n', 'm', 'Backspace'],
];

const el = {
  gate: document.getElementById('gate'),
  loginForm: document.getElementById('login-form'),
  password: document.getElementById('password'),
  loginError: document.getElementById('login-error'),
  game: document.getElementById('game'),
  signout: document.getElementById('signout'),
  board: document.getElementById('board'),
  keyboard: document.getElementById('keyboard'),
  toast: document.getElementById('toast'),
  result: document.getElementById('result'),
  resultTitle: document.getElementById('result-title'),
  resultText: document.getElementById('result-text'),
  again: document.getElementById('again'),
};

/** Server board plus the letters typed but not yet submitted. */
let view = null;
let draft = '';
let busy = false;      // a request is in flight, or a row is still revealing
let tiles = [];
let toastTimer = null;
let busyTimer = null;

/** How long a full row takes to turn over. */
const revealDuration = () => (view.word_length - 1) * REVEAL_STEP + REVEAL_TURN + 240;

/** Hold input for `ms`, so a keystroke cannot repaint a revealing row. */
function lockInput(ms) {
  busy = true;
  window.clearTimeout(busyTimer);
  busyTimer = window.setTimeout(() => {
    busy = false;
  }, ms);
}

// --- Screens --------------------------------------------------------------

function showGate(message = '') {
  el.game.hidden = true;
  el.gate.hidden = false;
  el.loginError.textContent = message;
  el.loginError.hidden = !message;
  el.password.value = '';
  el.password.focus();
}

function showGame() {
  el.gate.hidden = true;
  el.game.hidden = false;
}

/** Called whenever the API says our token is no longer good. */
function sessionLost() {
  WordleApi.logout();
  view = null;
  showGate('Session expired. Enter the password again.');
}

// --- Rendering ------------------------------------------------------------

/** Build the grid once; later updates mutate tiles so animations survive. */
function buildBoard() {
  el.board.replaceChildren();
  tiles = [];
  for (let r = 0; r < view.max_attempts; r += 1) {
    const row = document.createElement('div');
    row.className = 'row';
    row.setAttribute('role', 'row');
    const rowTiles = [];
    for (let c = 0; c < view.word_length; c += 1) {
      const tile = document.createElement('div');
      tile.className = 'tile';
      tile.setAttribute('role', 'gridcell');
      row.append(tile);
      rowTiles.push(tile);
    }
    el.board.append(row);
    tiles.push(rowTiles);
  }
}

function letterAt(rowIndex, column) {
  const attempt = view.attempts[rowIndex];
  if (attempt) return attempt.guess[column];
  if (rowIndex === view.attempts.length) return draft[column] || '';
  return '';
}

/**
 * Redraw the board.
 * `revealRow` flips that row's colours in one at a time; other rows get theirs
 * immediately, which is what a page reload needs.
 */
function paint(revealRow = -1) {
  for (let r = 0; r < tiles.length; r += 1) {
    const attempt = view.attempts[r];
    for (let c = 0; c < tiles[r].length; c += 1) {
      const tile = tiles[r][c];
      const letter = letterAt(r, c);
      tile.textContent = letter;
      tile.toggleAttribute('data-filled', Boolean(letter));
      tile.setAttribute(
        'aria-label',
        attempt ? `${letter}, ${attempt.colours[c]}` : letter || 'empty',
      );

      if (!attempt) {
        tile.removeAttribute('data-colour');
        tile.removeAttribute('data-reveal');
      } else if (r === revealRow) {
        tile.removeAttribute('data-colour');
        tile.style.animationDelay = `${c * REVEAL_STEP}ms`;
        tile.setAttribute('data-reveal', '');
        window.setTimeout(
          () => tile.setAttribute('data-colour', attempt.colours[c]),
          c * REVEAL_STEP + REVEAL_TURN,
        );
      } else {
        tile.removeAttribute('data-reveal');
        tile.style.animationDelay = '';
        tile.setAttribute('data-colour', attempt.colours[c]);
      }
    }
  }
  paintKeyboard();
}

function buildKeyboard() {
  el.keyboard.replaceChildren();
  for (const keys of KEY_ROWS) {
    const row = document.createElement('div');
    row.className = 'keys';
    for (const key of keys) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'key';
      button.dataset.key = key;
      button.textContent = key === 'Backspace' ? '⌫' : key;
      if (key.length > 1) button.setAttribute('data-wide', '');
      button.setAttribute('aria-label', key === 'Backspace' ? 'Backspace' : key);
      row.append(button);
    }
    el.keyboard.append(row);
  }
  // One listener for the whole keyboard rather than one per key.
  el.keyboard.addEventListener('click', (event) => {
    const button = event.target.closest('.key');
    if (!button) return;
    handleKey(button.dataset.key);
    button.blur();   // keep focus off the key so Enter still reaches the game
  });
}

function paintKeyboard() {
  const states = view.letter_states || {};
  for (const button of el.keyboard.querySelectorAll('.key')) {
    const state = states[button.dataset.key];
    if (state) button.setAttribute('data-colour', state);
    else button.removeAttribute('data-colour');
  }
}

function toast(message, tone = 'info') {
  el.toast.textContent = message;
  el.toast.dataset.tone = tone;
  el.toast.toggleAttribute('data-show', Boolean(message));
  window.clearTimeout(toastTimer);
  if (message) {
    toastTimer = window.setTimeout(() => el.toast.removeAttribute('data-show'), 2200);
  }
}

function rejectRow() {
  const row = el.board.children[view.attempts.length];
  if (!row) return;
  row.setAttribute('data-invalid', '');
  window.setTimeout(() => row.removeAttribute('data-invalid'), 500);
}

/** Wait out the reveal before covering the board with the result. */
function showResult() {
  window.setTimeout(() => {
    if (view.is_won) {
      el.resultTitle.textContent = 'Solved';
      el.resultText.textContent = `In ${view.attempts.length} of ${view.max_attempts}.`;
    } else {
      el.resultTitle.textContent = 'Out of guesses';
      const word = document.createElement('strong');
      word.textContent = view.answer;
      el.resultText.replaceChildren('The word was ', word, '.');
    }
    el.result.hidden = false;
    el.again.focus();
  }, revealDuration());
}

// --- Input ----------------------------------------------------------------

function handleKey(key) {
  if (busy || !view || view.is_over) return;

  if (key === 'Enter') {
    submit();
  } else if (key === 'Backspace') {
    if (!draft) return;
    draft = draft.slice(0, -1);
    paint();
  } else if (/^[a-z]$/.test(key) && draft.length < view.word_length) {
    draft += key;
    paint();
  }
}

async function submit() {
  if (draft.length < view.word_length) {
    toast(`Needs ${view.word_length} letters`, 'error');
    rejectRow();
    return;
  }

  busy = true;
  try {
    view = await WordleApi.submitGuess(view.game_id, draft);
    draft = '';
    paint(view.attempts.length - 1);
    lockInput(revealDuration());
    toast('');
    if (view.is_over) showResult();
  } catch (error) {
    // On success lockInput owns `busy`; on failure release it right away.
    busy = false;
    if (error.status === 401) {
      sessionLost();
    } else if (error.status === 400) {
      toast(error.message, 'error');   // e.g. "Not in word list"
      rejectRow();
    } else if (error.status === 404) {
      toast('That game expired. Starting a new one.', 'error');
      await start(true);
    } else {
      toast(error.message, 'error');
    }
  }
}

// --- Startup --------------------------------------------------------------

/** Resume the stored game when possible, otherwise deal a new one. */
async function start(force = false) {
  let saved = null;
  if (!force) {
    try {
      saved = window.localStorage.getItem(STORAGE_KEY);
    } catch {
      // No storage, no resume. Not fatal.
    }
  }

  view = null;
  if (saved) {
    view = await WordleApi.readGame(saved).catch((error) => {
      if (error.status === 401) throw error;
      return null;   // expired or unknown: just deal a new one
    });
  }
  if (!view) {
    view = await WordleApi.createGame();
  }

  draft = '';
  busy = false;
  window.clearTimeout(busyTimer);
  try {
    window.localStorage.setItem(STORAGE_KEY, view.game_id);
  } catch {
    // Private browsing can refuse storage; the game still plays, just no resume.
  }

  el.result.hidden = true;
  buildBoard();
  paint();
  if (view.is_over) showResult();
}

/** Enter the game, handling a token that turned out to be stale. */
async function enterGame() {
  showGame();
  try {
    await start();
  } catch (error) {
    if (error.status === 401) sessionLost();
    else toast(error.message, 'error');
  }
}

el.loginForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = el.loginForm.querySelector('button');
  button.disabled = true;
  try {
    await WordleApi.login(el.password.value);
    el.loginError.hidden = true;
    await enterGame();
  } catch (error) {
    el.loginError.textContent =
      error.status === 401 ? 'Wrong password.' : error.message;
    el.loginError.hidden = false;
    el.password.select();
  } finally {
    button.disabled = false;
  }
});

el.signout.addEventListener('click', () => {
  WordleApi.logout();
  view = null;
  showGate();
});

el.again.addEventListener('click', () => {
  start(true).catch((error) => {
    if (error.status === 401) sessionLost();
    else toast(error.message, 'error');
  });
});

document.addEventListener('keydown', (event) => {
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  if (el.game.hidden) return;   // the gate owns the keyboard while it is up
  const key = event.key;

  // A focused button owns its own Enter and Space: "Play again", "Sign out".
  if (key === 'Enter' && event.target instanceof HTMLButtonElement) return;

  if (key === 'Enter' || key === 'Backspace' || /^[a-zA-Z]$/.test(key)) {
    event.preventDefault();
    handleKey(key.length === 1 ? key.toLowerCase() : key);
  }
});

buildKeyboard();

// Skip the password screen if the stored token is still good.
WordleApi.sessionIsValid()
  .then((valid) => (valid ? enterGame() : showGate()))
  .catch(() => showGate('Cannot reach the server.'));
