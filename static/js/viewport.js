/*
 * Keeping the app sized to what is actually visible, and the composer
 * reachable while the on-screen keyboard is up.
 */

import { inputEl } from './elements.js';
import { stickToBottom, updateJumpButton } from './transcript.js';

/*
 * dvh handles the URL bar, but iOS Safari's on-screen keyboard overlays the
 * page instead of shrinking dvh, which would leave the composer hidden
 * behind the keyboard. visualViewport is the only thing that reports the
 * genuinely visible height in both cases.
 */
function syncAppHeight() {
  const vv = window.visualViewport;
  if (!vv) return;
  document.documentElement.style.setProperty('--app-h', vv.height + 'px');
  /*
   * iOS Safari scrolls the page itself to keep a focused input above the
   * keyboard, which -- with html/body now pinned via position: fixed --
   * just leaves blank space where the page tried and failed to scroll.
   * Snapping back to (0, 0) on every visual-viewport change (which fires
   * exactly when that auto-scroll attempt happens) cancels it out.
   */
  window.scrollTo(0, 0);
}

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
