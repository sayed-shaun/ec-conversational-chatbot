/*
 * The chat turn: sending a question, streaming the reply, and the session
 * it belongs to.
 */

import { API_BASE } from './config.js';
import { formEl, inputEl, sendBtn, resetBtn, messagesEl } from './elements.js';
import { el } from './dom.js';
import { addRow, addUserMessage, stickToBottom } from './transcript.js';
import { renderAnswer } from './answer.js';

// The session lives only in this page's memory: a refresh or a closed tab
// forgets it, so the next visit starts a fresh conversation.
let sessionId = null;
try {
  localStorage.removeItem('ec_conversational_session_id');
} catch (e) {

}

const CHAT_CLOSED_MESSAGE =
  'প্রশ্নের সর্বোচ্চ সীমায় পৌঁছানোয় এই চ্যাটটি বন্ধ হয়েছে এবং আগের কথোপকথন মুছে ফেলা হয়েছে। নতুন প্রশ্ন করলে নতুন চ্যাট শুরু হবে।';

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

const STAGE_LABELS = { faq: 'FAQ', search: 'top-k', llm: 'LLM', check: 'check' };
const secs = (ms) => (ms / 1000).toFixed(2) + 's';

/*
 * Runs one turn. `mode` tells the backend which system prompt to answer under
 * -- 'voice' replies are read aloud by TTS, so they are shaped differently
 * from typed ones (see src/chatbot/prompt.py).
 *
 * Voice mode passes `voice` = {asrMs, since}: the ASR stage to show first,
 * and when the turn really began, so the total covers the transcription too.
 * The returned addTiming() appends a later stage (TTS) to this turn's line.
 */
export async function ask(text, mode = 'text', turnId = newTurnId(), voice = null) {
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
  const since = voice ? voice.since : startedAt;
  const stages = voice ? [['ASR', voice.asrMs]] : [];
  let timing = null;
  const renderTiming = () => {
    if (!timing) timing = el('div', 'timing', bubble);
    timing.textContent = '\u23F1 ' +
      stages.map(([label, ms]) => label + ' ' + secs(ms)).join(' · ') +
      (stages.length ? ' · ' : '') + 'total ' + secs(performance.now() - since);
  };
  const addTiming = (label, ms) => {
    stages.push([label, ms]);
    renderTiming();
  };
  let answerRaw = '';
  let failed = false;
  let finalReply = '';
  let servedTag = '';

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
          collapseThinking();
        }
        answerRaw += ev.text;
        renderAnswer(answerEl, answerRaw);
        break;

      case 'error':
        failed = true;
        el('span', 'stream-err', bubble).textContent =
          '⚠ ' + (ev.message || 'stream error');
        break;

      case 'done': {
        if (!answerRaw.trim()) {
          answerRaw = ev.reply || '(কোনো উত্তর পাওয়া যায়নি)';
          renderAnswer(answerEl, answerRaw);
        }
        finalReply = ev.reply || answerRaw;
        servedTag = ev.tag || '';

        for (const [stage, ms] of Object.entries(ev.timings || {})) {
          stages.push([STAGE_LABELS[stage] || stage, ms]);
        }
        renderTiming();

        // The server used up this chat's question limit and deleted its history.
        if (ev.ended) {
          sessionId = null;
          addRow('bot').textContent = CHAT_CLOSED_MESSAGE;
        }

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

  return { text: finalReply, failed, addTiming, tag: servedTag };
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

resetBtn.addEventListener('click', async () => {
  if (sessionId) {
    try {
      await fetch(API_BASE + '/api/v1/reset', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ session_id: sessionId }),
      });
    } catch (e) {

    }
  }
  messagesEl.innerHTML = '';
  greet();
  inputEl.focus();
});

// Leaving the page (refresh, close, navigate away) ends the chat, so ask the
// server to drop its copy of the transcript instead of waiting for the idle TTL.
window.addEventListener('pagehide', () => {
  if (!sessionId) return;
  const body = new Blob([JSON.stringify({ session_id: sessionId })], {
    type: 'application/json',
  });
  navigator.sendBeacon(API_BASE + '/api/v1/reset', body);
});

export function greet() {
  addRow('bot').textContent =
    'আসসালামু আলাইকুম। এনআইডি বা ভোটার সেবা সম্পর্কে আপনার প্রশ্ন লিখুন।';
}
