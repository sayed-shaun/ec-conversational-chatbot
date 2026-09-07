/*
 * The transcript: appending rows, and the scroll behaviour around them.
 */

import { messagesEl, jumpBtn, inputEl, voiceOverlay } from './elements.js';
import { el } from './dom.js';

const nearBottom = () =>
  messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 70;

/*
 * Whether the transcript should follow new content.
 *
 * Every auto-scroll goes through this. They used to be unconditional
 * `scrollTop = scrollHeight` calls scattered over the message, token and
 * stream-end paths, so scrolling up to re-read something was undone by the
 * next token -- the list read as though it could not be scrolled at all.
 *
 * Held as state rather than sampled at each call site because the useful
 * moment to ask is when the READER last moved, not when the DOM happens to
 * change: by the time a new row has been appended the answer is already
 * "not near the bottom" for reasons that have nothing to do with intent.
 */
let pinnedToBottom = true;

export function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

export function stickToBottom() {
  if (pinnedToBottom) scrollToBottom();
}

export function updateJumpButton() {
  // Nothing to jump to when the transcript is too short to scroll.
  const scrollable = messagesEl.scrollHeight > messagesEl.clientHeight + 1;
  jumpBtn.hidden = pinnedToBottom || !scrollable;
  if (jumpBtn.hidden) jumpBtn.classList.remove('unread');
}

/*
 * The transcript is the only scrolling region on the page: html and body
 * are pinned (position: fixed, overflow: hidden) so iOS cannot scroll the
 * page out from behind the keyboard. The cost of that shows up on a
 * desktop, where the panel is capped at 860px and centred -- at 1366px wide
 * roughly 500px of background, 37% of the window, has no scrollable
 * ancestor, so the wheel does nothing there. The header, the composer and
 * the margins above and below the panel are dead in the same way, and
 * "the mouse wheel doesn't work" is the fair reading of that.
 *
 * Forward those events to the transcript instead.
 */
window.addEventListener('wheel', (ev) => {
  // Inside the transcript the browser already does the right thing, and
  // that includes its nested scrollers (reasoning boxes, code blocks),
  // which must keep first claim on the wheel.
  if (messagesEl.contains(ev.target)) return;

  if (!voiceOverlay.hidden) return;

  // Leave the composer alone while it has its own overflow to consume --
  // a long draft scrolls within the textarea.
  if (inputEl.contains(ev.target) &&
      inputEl.scrollHeight > inputEl.clientHeight + 1) return;

  // deltaMode is not always pixels: it reports lines on some setups and
  // pages on others, where a raw deltaY would move about three pixels a
  // notch and read as broken in a different way.
  const unit =
    ev.deltaMode === 1 ? 16 :
    ev.deltaMode === 2 ? messagesEl.clientHeight : 1;

  const before = messagesEl.scrollTop;
  messagesEl.scrollTop += ev.deltaY * unit;
  // Only claim the event if it actually moved something, so a wheel at the
  // very top or bottom still falls through to the browser.
  if (messagesEl.scrollTop !== before) ev.preventDefault();
}, { passive: false });

jumpBtn.addEventListener('click', () => {
  pinnedToBottom = true;
  jumpBtn.classList.remove('unread');
  messagesEl.scrollTo({ top: messagesEl.scrollHeight, behavior: 'smooth' });
  updateJumpButton();
});

// Programmatic scrolls fire this too, which is what keeps the flag true
// after scrollToBottom() and re-arms following once the reader returns.
messagesEl.addEventListener('scroll', () => {
  pinnedToBottom = nearBottom();
  updateJumpButton();
});

export function addRow(who) {
  const row = el('div', 'row ' + who, messagesEl);
  const avatar = el('div', 'avatar avatar-' + who, row);
  avatar.textContent = who === 'user' ? '\u{1F464}' : '\u{1F5F3}️';
  avatar.setAttribute('aria-hidden', 'true');
  const bubble = el('div', 'bubble', row);
  stickToBottom();
  if (!pinnedToBottom) jumpBtn.classList.add('unread');
  updateJumpButton();
  return bubble;
}

export function addUserMessage(text) {
  // Sending re-pins: someone who has just spoken or typed means to see the
  // result, wherever they had scrolled to read.
  pinnedToBottom = true;
  addRow('user').textContent = text;
}
