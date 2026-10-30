/**
 * The game: board, typing, and the end-of-game card.
 *
 * Holds no game rules. The server decides which words are valid and what
 * colour each letter gets; this draws what it returns and collects key presses.
 */

import { api } from './api.js';
import { createKeyboard } from './keyboard.js';
import { loadSavedGame, saveGame } from './saved-game.js';
import { toast } from './toast.js';

const REVEAL_STEP = 220;   // gap between tiles flipping, ms
const REVEAL_TURN = 240;   // point in the flip where the colour appears, ms

/**
 * Build the game on the page. `account` is told when the API refuses the
 * sign-in, and owns the keyboard while its menu is open.
 *
 * Returns `{ play(force) }`: resume the saved game, or deal a new one.
 */
export function createGame({ account }) {
  const board = document.getElementById('board');
  const note = document.getElementById('game-note');
  const result = document.getElementById('result');
  const resultTitle = document.getElementById('result-title');
  const resultScore = document.getElementById('result-score');
  const resultText = document.getElementById('result-text');
  const again = document.getElementById('again');
  const keyboard = createKeyboard(document.getElementById('keyboard'), handleKey);

  /** Server board plus the letters typed but not yet submitted. */
  let view = null;
  let draft = '';
  let busy = false;      // a request is in flight, or a row is still revealing
  let clockStarted = false;   // this game's clock has been asked to start
  let tiles = [];
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

  // --- Rendering ----------------------------------------------------------

  /** Build the grid once; later updates mutate tiles so animations survive. */
  function buildBoard() {
    board.replaceChildren();
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
      board.append(row);
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
    keyboard.paint(view.letter_states);
    // Only a signed-in player has stats for a game to miss. Their game is not
    // theirs only when they started it signed out and guessed before signing in.
    note.hidden = !account.isSignedIn() || view.owned;
  }

  function rejectRow() {
    const row = board.children[view.attempts.length];
    if (!row) return;
    row.setAttribute('data-invalid', '');
    window.setTimeout(() => row.removeAttribute('data-invalid'), 500);
  }

  /**
   * Show what the win was worth.
   *
   * Only on a win: a loss scores zero, and a nought is not news. The server
   * sends the number already rounded; two decimals is how it is meant to read.
   */
  function paintScore() {
    const earned = view.is_won && view.score ? view.score.score : null;
    resultScore.hidden = earned === null;
    if (earned === null) return;

    const unit = document.createElement('span');
    unit.textContent = earned === 1 ? 'point' : 'points';
    resultScore.replaceChildren(earned.toFixed(2), ' ', unit);
  }

  /** Wait out the reveal before covering the board with the result. */
  function showResult() {
    window.setTimeout(() => {
      paintScore();
      if (view.is_won) {
        resultTitle.textContent = 'Solved';
        resultText.textContent = `In ${view.attempts.length} of ${view.max_attempts}.`;
      } else {
        resultTitle.textContent = 'Out of guesses';
        const word = document.createElement('strong');
        word.textContent = view.answer;
        resultText.replaceChildren('The word was ', word, '.');
      }
      result.hidden = false;
      again.focus();
    }, revealDuration());
  }

  // --- Input --------------------------------------------------------------

  /**
   * Start the clock on the first letter typed, which is when play really begins.
   *
   * Fire and forget. A score is worth less than a responsive board, so a slow or
   * failed call must not hold up the keystroke that triggered it; the server
   * falls back to timing from the first guess. Asked for once per game here, and
   * ignored after the first by the server, so a resumed game keeps the clock it
   * already started.
   */
  function startClock() {
    if (clockStarted) return;
    clockStarted = true;
    api.startGame(view.game_id).catch(() => {
      // Nothing to tell the player: the game plays exactly the same either way.
    });
  }

  function handleKey(key) {
    if (busy || !view || view.is_over) return;

    if (key === 'Enter') {
      submit();
    } else if (key === 'Backspace') {
      if (!draft) return;
      draft = draft.slice(0, -1);
      paint();
    } else if (/^[a-z]$/.test(key) && draft.length < view.word_length) {
      startClock();
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
      view = await api.submitGuess(view.game_id, draft);
      draft = '';
      paint(view.attempts.length - 1);
      lockInput(revealDuration());
      toast('');
      if (view.is_over) showResult();
    } catch (error) {
      // On success lockInput owns `busy`; on failure release it right away.
      busy = false;
      if (error.signInRejected) {
        await account.signInLost(error.message);
        await play();
      } else if (error.status === 400) {
        toast(error.message, 'error');   // e.g. "Enter a valid word"
        rejectRow();
      } else if (error.status === 404) {
        toast('That game expired. Starting a new one.', 'error');
        await play(true);
      } else {
        toast(error.message, 'error');
      }
    }
  }

  // --- Starting -----------------------------------------------------------

  /** Resume the stored game when possible, otherwise deal a new one. */
  async function start(force = false) {
    const saved = force ? null : loadSavedGame();

    view = null;
    if (saved) {
      // Expired or unknown: just deal a new one.
      view = await api.readGame(saved).catch(() => null);
    }
    if (!view) {
      view = await api.createGame();
    }

    draft = '';
    busy = false;
    clockStarted = false;
    window.clearTimeout(busyTimer);
    saveGame(view.game_id);

    result.hidden = true;
    buildBoard();
    paint();
    if (view.is_over) showResult();
  }

  /**
   * Start or resume a game. If the API refuses the sign-in on the way, carry on
   * signed out rather than leaving the player without a board.
   */
  async function play(force = false) {
    try {
      await start(force);
    } catch (error) {
      if (!error.signInRejected) {
        toast(error.message, 'error');
        return;
      }
      await account.signInLost(error.message);
      await start(force).catch((again) => toast(again.message, 'error'));
    }
  }

  again.addEventListener('click', () => play(true));

  document.addEventListener('keydown', (event) => {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    // The account menu and its confirmation own the keyboard while open, so
    // typing there never puts letters on the board.
    if (account.isOpen()) return;

    const key = event.key;
    // A focused button owns its own Enter and Space: "Play again".
    if (key === 'Enter' && event.target instanceof HTMLButtonElement) return;

    if (key === 'Enter' || key === 'Backspace' || /^[a-zA-Z]$/.test(key)) {
      event.preventDefault();
      handleKey(key.length === 1 ? key.toLowerCase() : key);
    }
  });

  return { play };
}
