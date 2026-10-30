/**
 * The on-screen keyboard: its layout, its keys, and their colours.
 *
 * Knows nothing of the game. It reports each key pressed to the callback it
 * was given, and paints whatever letter states it is handed.
 */

/**
 * Keyboard layout.
 *
 * Every key is placed on one shared column grid, so a letter is exactly as
 * wide in row 1 as in row 3. Nothing here is special-cased per key: a width,
 * an alignment and a bound are properties any key or row can have.
 */
const KEYBOARD = {
  /**
   * A row is either a string of keys, or an object with per-row overrides:
   *   { keys, align, within }
   */
  rows: [
    'q w e r t y u i o p',
    'a s d f g h j k l',
    'z x c v b n m Backspace',
    { keys: 'Enter', align: 'center' },
  ],

  /**
   * Key widths. Two forms:
   *   number   letter-units, e.g. 1.5 is one and a half letters wide
   *   '<n>%'   a share of the space the row is allowed to use
   * Anything not listed is one letter wide.
   */
  widths: {
    Backspace: 1.5,
    Enter: '50%',
  },

  /** Row defaults. Any row may override either. */
  align: 'center',          // 'left' | 'center' | 'right'
  within: 'previous-row',   // 'previous-row' | 'keyboard'

  /**
   * Grid columns per letter. Rows are centred by whole columns, so a row
   * summing to an odd number of them lands half a column off. Four places the
   * default layout exactly. Raise it for widths finer than a quarter letter.
   */
  precision: 4,
};

const ALIGNERS = {
  left: () => 0,
  center: (free) => Math.floor(free / 2),
  right: (free) => free,
};

const clamp = (n, low, high) => Math.min(Math.max(n, low), high);

const isShare = (width) => typeof width === 'string' && width.trim().endsWith('%');

/**
 * Turn the config into concrete grid placements.
 *
 * Pure: no DOM, so the arithmetic can be exercised on its own.
 * Returns { columns, rows: [[{ key, span, start }]] }, all in grid columns.
 */
export function keyboardLayout(config = KEYBOARD) {
  const perUnit = config.precision ?? 4;
  const widthOf = (key) => config.widths?.[key] ?? 1;

  const rows = config.rows
    .map((row) => (typeof row === 'string' ? { keys: row } : row))
    .map((row) => ({
      keys: row.keys.trim().split(/\s+/),
      align: row.align ?? config.align ?? 'center',
      within: row.within ?? config.within ?? 'keyboard',
    }));

  // The grid is as wide as the widest row of fixed-width keys. Share-width
  // keys are relative to their row, so they cannot define the grid.
  const fixedUnits = (keys) =>
    keys.reduce((total, key) => total + (isShare(widthOf(key)) ? 0 : widthOf(key)), 0);
  const columns = Math.max(1, Math.round(Math.max(...rows.map((r) => fixedUnits(r.keys))) * perUnit));

  const spanFor = (key, available) => {
    const width = widthOf(key);
    const span = isShare(width)
      ? Math.round((parseFloat(width) / 100) * available)
      : Math.round(width * perUnit);
    return clamp(span, 1, available);
  };

  const placed = [];
  for (const row of rows) {
    // A row may be held inside the one above, so a wide key cannot stick out
    // past the keys it sits under.
    const above = row.within === 'previous-row' ? placed[placed.length - 1] : null;
    let from = above ? above[0].start : 1;
    let to = above ? above[above.length - 1].start + above[above.length - 1].span - 1 : columns;
    let available = to - from + 1;

    let spans = row.keys.map((key) => spanFor(key, available));
    let used = spans.reduce((a, b) => a + b, 0);

    // Containment is a preference, not a cage. A row of fixed-width keys that
    // cannot fit inside the row above falls back to the whole grid rather than
    // overflowing its bounds.
    if (used > available) {
      from = 1;
      to = columns;
      available = columns;
      spans = row.keys.map((key) => spanFor(key, available));
      used = spans.reduce((a, b) => a + b, 0);
    }
    const align = ALIGNERS[row.align] ?? ALIGNERS.center;

    let cursor = from + align(Math.max(0, available - used));   // grid lines are 1-based
    placed.push(
      row.keys.map((key, i) => {
        const placement = { key, span: spans[i], start: cursor };
        cursor += spans[i];
        return placement;
      }),
    );
  }

  return { columns, rows: placed };
}

const KEY_LABELS = { Backspace: '⌫', Enter: 'Enter' };

/**
 * Build the keyboard inside `container`. `onKey` gets the key's name:
 * a letter, 'Enter' or 'Backspace'. Returns `{ paint(letterStates) }`.
 */
export function createKeyboard(container, onKey) {
  const layout = keyboardLayout();
  container.replaceChildren();
  container.style.setProperty('--keyboard-columns', layout.columns);

  for (const placements of layout.rows) {
    const row = document.createElement('div');
    row.className = 'keys';
    for (const { key, span, start } of placements) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'key';
      button.dataset.key = key;
      button.textContent = KEY_LABELS[key] ?? key;
      // Placement comes from the grid, never from the content width, so every
      // letter is the same size in every row.
      button.style.gridColumn = `${start} / span ${span}`;
      if (key.length > 1) button.setAttribute('data-wide', '');
      button.setAttribute('aria-label', key);
      row.append(button);
    }
    container.append(row);
  }
  // One listener for the whole keyboard rather than one per key.
  container.addEventListener('click', (event) => {
    const button = event.target.closest('.key');
    if (!button) return;
    onKey(button.dataset.key);
    button.blur();   // keep focus off the key so Enter still reaches the game
  });

  return {
    /** Colour each key by the best result its letter has had. */
    paint(states = {}) {
      for (const button of container.querySelectorAll('.key')) {
        const state = states[button.dataset.key];
        if (state) button.setAttribute('data-colour', state);
        else button.removeAttribute('data-colour');
      }
    },
  };
}
