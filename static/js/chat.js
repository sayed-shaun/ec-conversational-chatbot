/*
 * The chat turn: sending a question, streaming the reply, and the session
 * it belongs to.
 */

import { API_BASE } from './config.js';
import { formEl, inputEl, sendBtn, resetBtn, messagesEl } from './elements.js';
import { el, formatSeconds } from './dom.js';
import { addRow, addUserMessage, stickToBottom } from './transcript.js';
import { renderAnswer } from './answer.js';

/*
 * The session id lives in this tab and nowhere else.
 *
 * It used to be kept in localStorage, which meant closing the chat and
 * reopening it resumed the same conversation -- the transcript outlived the
 * visit. A citizen asking about their own NID at a shared or public machine
 * should not find the previous person's questions waiting, so the id is now
 * held in memory, the transcript is deleted server-side when the page goes
 * away (see endSession below), and any id left behind by the old build is
 * cleared out on load.
 */
let sessionId = null;
try {
  localStorage.removeItem('ec_conversational_session_id');
} catch (e) {
  // Private mode or blocked storage: nothing to clear, nothing to do.
}

// Read-only view for voice mode, which tags its ASR and TTS calls with the
// session they belong to (see src/chatbot/trace.py).
export const getSessionId = () => sessionId;
let busy = false;

function addRetryButton(bubble, text, mode) {
  const btn = el('button', 'retry-btn', bubble);
  btn.type = 'button';
  btn.textContent = '↻ আবার চেষ্টা করুন';
  btn.addEventListener('click', () => {
    bubble.remove();
    ask(text, mode);
  });
}

// Groups a turn's calls in the server-side trace (src/chatbot/trace.py).
// Voice mode supplies its own, so the ASR clip, this turn and the spoken
// reply share one id; a typed turn is a single call and mints its own here.
export const newTurnId = () =>
  (crypto.randomUUID ? crypto.randomUUID()
                     : String(Date.now()) + Math.random().toString(16).slice(2));

/*
 * Runs one turn. `mode` tells the backend which system prompt to answer under
 * -- 'voice' replies are read aloud by TTS, so they are shaped differently
 * from typed ones (see src/chatbot/prompt.py).
 */
export async function ask(text, mode = 'text', turnId = newTurnId()) {
  const bubble = addRow('bot');

  const think = el('details', 'think', bubble);
  const thinkSummary = el('summary', null, think);
  thinkSummary.textContent = 'চিন্তা করছে…';
  const thinkBody = el('div', 'think-body', think);
  const toolsEl = el('div', 'tools', bubble);
  const answerEl = el('div', 'answer cursor', bubble);

  think.style.display = 'none';
  think.open = true;

  let chip = null;
  let answerStarted = false;
  let toolRan = false;

  // Timing, so the wait after a tool call is visible rather than a mystery.
  const startedAt = performance.now();
  let toolResultAt = null;
  let firstTokenAt = null;
  let answerRaw = '';
  let failed = false;
  let finalReply = '';
  // Rendering is coalesced onto a frame rather than run per token.
  // renderAnswer reparses the whole markdown and rescans it for KaTeX, so
  // doing it on every token makes the cost quadratic in the answer's length
  // -- which is why a long reply showed a wait well past the time the
  // server had already finished.
  let renderFrame = 0;
  // The knowledge-base entry this answer came from, '' when the LLM wrote
  // it. Carried to the TTS call, which is where it decides caching.
  let finalTag = '';

  /** Draw the answer at most once a frame, with whatever has arrived. */
  const scheduleRender = () => {
    if (renderFrame) return;
    renderFrame = requestAnimationFrame(() => {
      renderFrame = 0;
      renderAnswer(answerEl, answerRaw);
    });
  };

  /** Draw immediately, dropping any frame still queued. */
  const renderNow = () => {
    if (renderFrame) {
      cancelAnimationFrame(renderFrame);
      renderFrame = 0;
    }
    renderAnswer(answerEl, answerRaw);
  };

  const handle = (ev) => {

    switch (ev.type) {
      case 'start':
        sessionId = ev.session_id;
        break;

      case 'reasoning':
        think.style.display = '';
        {
          // Same rule as the transcript: follow the tail only while the
          // reader is already at it, so scrolling back through the
          // reasoning is not undone by the next token.
          const tailing =
            thinkBody.scrollHeight - thinkBody.scrollTop - thinkBody.clientHeight < 30;
          thinkBody.textContent += ev.text;
          if (tailing) thinkBody.scrollTop = thinkBody.scrollHeight;
        }
        /*
         * After a tool result the model runs a second thinking pass before
         * the first answer token, which is the bulk of the wait on a
         * reasoning model. Without this the block stayed collapsed under a
         * static label and the UI looked frozen for that whole stretch.
         */
        if (!answerStarted) {
          thinkSummary.textContent = toolRan
            ? 'উত্তর তৈরি করছে…'
            : 'চিন্তা করছে…';
        }
        break;

      case 'tool_call': {
        toolRan = true;
        collapseThinking();
        chip = el('details', 'tool running', toolsEl);
        const summary = el('summary', null, chip);
        el('span', 'tool-name', summary).textContent = '\u{1F527} tool';
        const body = el('div', 'tool-body', chip);
        let args = ev.arguments || '';
        try {
          args = JSON.stringify(JSON.parse(args));
        } catch (e) {

        }
        el('code', 'tool-args', body).textContent = args;
        break;
      }

      case 'tool_result': {
        toolResultAt = performance.now();
        if (!chip) break;
        chip.classList.remove('running');
        const body = chip.querySelector('.tool-body');
        const res = el('span', 'tool-res', body);

        if (ev.error) {
          const bad = el('span', 'bad', res);
          bad.textContent = '✗ ' + ev.error;
          break;
        }

        const score = ev.best_score == null ? '?' : Number(ev.best_score).toFixed(3);
        const verdict = el('span', ev.confident ? 'ok' : 'weak', res);
        verdict.textContent =
          (ev.confident ? '✓ confident' : '⚠ low confidence') +
          ' · ' + (ev.best_tag || '-') +
          ' · ' + score +
          (ev.threshold != null ? ' / ' + Number(ev.threshold).toFixed(2) : '');

        if (ev.candidates && ev.candidates.length) {
          const cands = el('div', 'cands', res);
          el('div', null, cands).textContent =
            ev.alternatives + ' other candidate(s):';
          ev.candidates.forEach((c) => {
            const line = el('div', null, cands);
            const s = c.score == null ? '?' : Number(c.score).toFixed(3);
            line.textContent = '· ' + c.tag + '  ' + s;
          });
        }
        break;
      }

      case 'token':
        if (!answerStarted) {
          answerStarted = true;
          firstTokenAt = performance.now();
          collapseThinking();
        }
        answerRaw += ev.text;
        scheduleRender();
        break;

      case 'error':
        failed = true;
        el('span', 'stream-err', bubble).textContent =
          '⚠ ' + (ev.message || 'stream error');
        break;

      case 'done': {
        if (!answerRaw.trim()) {
          answerRaw = ev.reply || '(কোনো উত্তর পাওয়া যায়নি)';
        }
        renderNow();
        finalReply = ev.reply || answerRaw;
        finalTag = ev.tag || '';

        const total = performance.now() - startedAt;
        const timing = el('div', 'timing', bubble);
        timing.textContent = '\u23F1 ' + formatSeconds(total) + ' সেকেন্ড';

        // Breakdown on hover: most of a slow turn is the model thinking
        // after the tool result, which is otherwise invisible.
        const parts = [];
        if (toolResultAt !== null) {
          parts.push('তথ্য খোঁজা: ' + formatSeconds(toolResultAt - startedAt) + ' সে.');
        }
        if (firstTokenAt !== null) {
          parts.push('উত্তর শুরু: ' + formatSeconds(firstTokenAt - startedAt) + ' সে.');
          parts.push('উত্তর লেখা: ' + formatSeconds(performance.now() - firstTokenAt) + ' সে.');
        }
        if (parts.length) timing.title = parts.join(' · ');
        break;
      }
    }

    stickToBottom();
  };

  function collapseThinking() {
    if (think.style.display === 'none') return;
    think.open = false;
    thinkSummary.textContent = 'চিন্তার ধাপ দেখুন';
  }

  try {
    const res = await fetch(API_BASE + '/api/v1/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        /*
         * ngrok's free tier serves a browser interstitial warning page
         * (ERR_NGROK_6024) to any request carrying a browser User-Agent,
         * so every API call from a real browser would get HTML back
         * instead of JSON. This header opts out. Harmless when API_BASE
         * is not an ngrok tunnel.
         */
        'ngrok-skip-browser-warning': 'true',
      },
      body: JSON.stringify({
        session_id: sessionId,
        message: text,
        mode: mode,
        turn_id: turnId,
      }),
    });
    if (!res.ok || !res.body) throw new Error('HTTP ' + res.status);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const frames = buffer.split('\n\n');
      buffer = frames.pop();

      for (const frame of frames) {
        for (const line of frame.split('\n')) {
          if (!line.startsWith('data: ')) continue;
          const raw = line.slice(6);
          if (raw === '[DONE]') continue;
          try {
            handle(JSON.parse(raw));
          } catch (e) {

          }
        }
      }
    }
  } catch (err) {
    failed = true;
    el('span', 'stream-err', bubble).textContent =
      'দুঃখিত, সার্ভারের সাথে সংযোগ করা যায়নি।';
  } finally {
    answerEl.classList.remove('cursor');
    if (!thinkBody.textContent.trim()) think.style.display = 'none';
    if (failed) addRetryButton(bubble, text, mode);
    stickToBottom();
  }

  return { text: finalReply, failed, tag: finalTag };
}

async function submit() {
  const text = inputEl.value.trim();
  if (!text || busy) return;

  busy = true;
  sendBtn.disabled = true;
  addUserMessage(text);
  inputEl.value = '';
  inputEl.style.height = 'auto';

  try {
    await ask(text);
  } finally {
    busy = false;
    sendBtn.disabled = false;
    inputEl.focus();
  }
}

formEl.addEventListener('submit', (e) => {
  e.preventDefault();
  submit();
});

inputEl.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    submit();
  }
});

inputEl.addEventListener('input', () => {
  inputEl.style.height = 'auto';
  inputEl.style.height = Math.min(inputEl.scrollHeight, 140) + 'px';
});

/*
 * Ask the server to delete this session's transcript.
 *
 * `keepalive` is what makes this work from the unload handler below: a normal
 * fetch is cancelled when the page goes away, which is exactly the moment the
 * request matters most. sendBeacon would also survive, but it cannot send
 * `Content-Type: application/json` cross-origin without tripping a preflight
 * it is not allowed to make -- and the UI is meant to be hostable on another
 * origin (see CORS_ALLOW_ORIGINS), so that would fail silently on Vercel.
 */
function endSession() {
  if (!sessionId) return;
  try {
    fetch(API_BASE + '/api/v1/reset', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'ngrok-skip-browser-warning': 'true',
      },
      body: JSON.stringify({ session_id: sessionId }),
      keepalive: true,
    }).catch(() => {});
  } catch (e) {

  }
}

resetBtn.addEventListener('click', () => {
  endSession();
  // A new id is minted by the next turn's `start` event; dropping it here is
  // what makes the reset a new conversation rather than a cleared screen.
  sessionId = null;
  messagesEl.innerHTML = '';
  greet();
  inputEl.focus();
});

/*
 * Closing the chat deletes it.
 *
 * `pagehide` rather than `beforeunload`: it is the one that fires reliably on
 * mobile Safari and Chrome, where a tab is frozen and discarded rather than
 * unloaded, and `beforeunload` often never runs at all.
 *
 * This is best-effort by nature -- a crash, a killed tab or a dropped
 * connection sends nothing. SESSION_TTL_MINUTES on the server is the backstop
 * that catches those, so a transcript is deleted promptly when the browser
 * manages to say goodbye, and on the idle timer when it does not.
 */
window.addEventListener('pagehide', endSession);

export function greet() {
  addRow('bot').textContent =
    'আসসালামু আলাইকুম। এনআইডি বা ভোটার সেবা সম্পর্কে আপনার প্রশ্ন লিখুন।';
}
