/**
 * The id of the game in progress, kept so a reload resumes the same board.
 *
 * Storage can be refused (private browsing, blocked site data); every call
 * shrugs that off, because losing the resume is not worth breaking the game.
 */

const KEY = 'wordle.gameId';

export function loadSavedGame() {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function saveGame(id) {
  try {
    window.localStorage.setItem(KEY, id);
  } catch {
    // The game still plays, just without resume.
  }
}

export function forgetSavedGame() {
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // Nothing stored; nothing to remove.
  }
}
