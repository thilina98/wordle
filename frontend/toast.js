/**
 * A short message under the header. Every page has one `#toast` element.
 */

let timer = null;

export function toast(message, tone = 'info') {
  const el = document.getElementById('toast');
  if (!el) return;
  el.textContent = message;
  el.dataset.tone = tone;
  el.toggleAttribute('data-show', Boolean(message));
  window.clearTimeout(timer);
  if (message) {
    timer = window.setTimeout(() => el.removeAttribute('data-show'), 2200);
  }
}
