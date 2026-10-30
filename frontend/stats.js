/**
 * The statistics page: the signed-in player's figures across every game.
 *
 * Filtering by mode and difficulty comes later; `api.readMyStats` already
 * takes both. Streaks are not shown until then, because the server only sends
 * them for a single mode and difficulty.
 */

import { createAccount } from './account.js';
import { api } from './api.js';
import { auth } from './auth.js';

/** Shown where the server sent null: nothing to divide by yet. */
const DASH = '–';

const status = document.getElementById('stats-status');
const body = document.getElementById('stats-body');
const distribution = document.getElementById('stat-distribution');

const formatScore = (n) => (n === null ? DASH : n.toFixed(2));

/** Milliseconds as "42.3s", or "1:05" from a minute up. */
function formatTime(ms) {
  if (ms === null) return DASH;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const whole = Math.round(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
}

/** Show a message in place of the figures. */
function say(message) {
  body.hidden = true;
  status.textContent = message;
  status.hidden = false;
}

/**
 * One bar per attempt number, from 1 to the highest any win took. Bars are
 * sized against the most common attempt, so the longest always fills the row.
 */
function paintDistribution(counts) {
  const byAttempt = new Map(Object.entries(counts).map(([n, count]) => [Number(n), count]));
  distribution.replaceChildren();
  if (!byAttempt.size) {
    const none = document.createElement('p');
    none.className = 'stats-note';
    none.textContent = 'No wins yet.';
    distribution.append(none);
    return;
  }
  const most = Math.max(...byAttempt.values());
  const last = Math.max(...byAttempt.keys());
  for (let attempt = 1; attempt <= last; attempt += 1) {
    const count = byAttempt.get(attempt) || 0;
    const row = document.createElement('div');
    row.className = 'distribution-row';
    row.setAttribute('aria-label', `Won on guess ${attempt}: ${count}`);

    const label = document.createElement('span');
    label.textContent = attempt;
    const bar = document.createElement('span');
    bar.className = 'distribution-bar';
    bar.style.width = `${Math.max(8, (count / most) * 100)}%`;
    bar.textContent = count;
    bar.toggleAttribute('data-empty', count === 0);
    row.append(label, bar);
    distribution.append(row);
  }
}

function paint(stats) {
  const figures = {
    games: stats.games,
    'win-percentage': stats.win_percentage === null ? DASH : Math.round(stats.win_percentage),
    wins: stats.wins,
    losses: stats.losses,
    'total-score': formatScore(stats.total_score),
    'highest-score': formatScore(stats.highest_score),
    'average-score': formatScore(stats.average_score),
    'first-attempt-wins': stats.first_attempt_wins,
    'last-attempt-wins': stats.last_attempt_wins,
    'fastest-win': formatTime(stats.fastest_win_ms),
    'average-win': formatTime(stats.average_win_ms),
  };
  for (const [name, value] of Object.entries(figures)) {
    document.querySelector(`[data-stat="${name}"]`).textContent = value;
  }
  paintDistribution(stats.guess_distribution);
  status.hidden = true;
  body.hidden = false;
}

async function load() {
  if (!auth.enabled) {
    say('Statistics need an account, and sign-in is not set up on this server.');
    return;
  }
  if (!auth.isSignedIn()) {
    say('Sign in to see your statistics.');
    return;
  }
  say('Loading…');
  try {
    const stats = await api.readMyStats();
    if (stats.games === 0) say('No games yet. Finish a game to see your statistics here.');
    else paint(stats);
  } catch (error) {
    if (error.signInRejected) {
      await account.signInLost(error.message);
      say('Sign in to see your statistics.');
    } else {
      say('Could not load your statistics. Try again shortly.');
    }
  }
}

api.useToken(() => auth.accessToken());

const account = createAccount({ page: 'stats' });
// The stats only need the sign-in, so they load alongside the player, not after it.
const started = account.start();
await account.signInKnown();
await Promise.all([started, load()]);
