/*
 * Keeping the app sized to what is actually visible, and the composer
 * reachable while the on-screen keyboard is up.
 */

import { inputEl } from './elements.js';
import { isTouching, stickToBottom, updateJumpButton } from './transcript.js';

/*
 * dvh handles the URL bar, but iOS Safari's on-screen keyboard overlays the
 * page instead of shrinking dvh, which would leave the composer hidden
 * behind the keyboard. visualViewport is the only thing that reports the
 * genuinely visible height in both cases.
 */
let appliedHeight = 0;
let pendingHeight = 0;

/*
 * A keyboard opening or closing moves the visible height by a lot; a mobile
 * URL bar sliding away moves it by a little. Only the first is worth
 * resizing the app for mid-gesture: writing --app-h relayouts the entire
 * transcript, and doing that on every frame of a scroll is what makes a long
 * conversation stutter and stall under the finger.
 */
const KEYBOARD_MIN_DELTA = 120;

function applyHeight(h) {
  appliedHeight = h;
  pendingHeight = 0;
  document.documentElement.style.setProperty('--app-h', h + 'px');
}

function syncAppHeight() {
  const vv = window.visualViewport;
  if (!vv) return;

  const h = vv.height;
  if (Math.abs(h - appliedHeight) >= 1) {
    // A small change while the reader is scrolling is the URL bar, not the
    // keyboard. Hold it until the gesture ends rather than resizing under
    // them.
    if (isTouching() && Math.abs(h - appliedHeight) < KEYBOARD_MIN_DELTA) {
      pendingHeight = h;
    } else {
      applyHeight(h);
    }
  }

  /*
   * iOS Safari scrolls the page itself to keep a focused input above the
   * keyboard, which -- with html/body now pinned via position: fixed --
   * just leaves blank space where the page tried and failed to scroll.
   * Snapping back to (0, 0) cancels it out. Only when it has actually
   * happened: an unconditional scrollTo on every visual-viewport event
   * interferes with the transcript's own scrolling.
   */
  if (window.scrollX !== 0 || window.scrollY !== 0) window.scrollTo(0, 0);
}

// Whatever was held back during a gesture is applied once it is over.
window.addEventListener('touchend', () => {
  if (pendingHeight) applyHeight(pendingHeight);
}, { passive: true });

// The transcript can stop being scrollable when the viewport grows, which
// would otherwise strand the button on screen with nothing to do.
window.addEventListener('resize', updateJumpButton);

if (window.visualViewport) {
  window.visualViewport.addEventListener('resize', syncAppHeight);
  window.visualViewport.addEventListener('scroll', syncAppHeight);
  syncAppHeight();
}

// Keep the latest message in view when the keyboard opens over the page.
inputEl.addEventListener('focus', () => {
  setTimeout(stickToBottom, 250);
});
