const messagesEl = document.getElementById('messages');
const formEl = document.getElementById('chat-form');
const inputEl = document.getElementById('question-input');
const sendBtn = document.getElementById('send-btn');
const resetBtn = document.getElementById('reset-btn');

const paramEls = {
  top_k: document.getElementById('param-top-k'),
  min_score: document.getElementById('param-min-score'),
  min_score_ratio: document.getElementById('param-min-score-ratio'),
  handle_unknown: document.getElementById('param-handle-unknown'),
  show_candidates: document.getElementById('param-show-candidates'),
};

let sessionId = localStorage.getItem('ec_faq_session_id') || null;
let busy = false;

function el(tag, cls, parent) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (parent) parent.appendChild(node);
  return node;
}

const nearBottom = () =>
  messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 70;

function stickToBottom(wasNear) {
  if (wasNear) messagesEl.scrollTop = messagesEl.scrollHeight;
}

function readParams() {
  const num = (input, fallback) => {
    const v = parseFloat(input.value);
    return Number.isFinite(v) ? v : fallback;
  };
  return {
    top_k: Math.max(1, Math.round(num(paramEls.top_k, 10))),
    min_score: num(paramEls.min_score, null),
    min_score_ratio: num(paramEls.min_score_ratio, 1),
    handle_unknown: paramEls.handle_unknown.checked,
    show_candidates: paramEls.show_candidates.checked,
  };
}

function addRow(who) {
  const row = el('div', 'row ' + who, messagesEl);
  const avatar = el('div', 'avatar avatar-' + who, row);
  avatar.textContent = who === 'user' ? '\u{1F464}' : '\u{1F5F3}️';
  avatar.setAttribute('aria-hidden', 'true');
  const bubble = el('div', 'bubble', row);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return bubble;
}

function addUserMessage(text) {
  addRow('user').textContent = text;
}

function renderAnswer(answerEl, raw) {
  answerEl.innerHTML = renderMarkdown(raw);
}

function addRetryButton(bubble, text) {
  const btn = el('button', 'retry-btn', bubble);
  btn.type = 'button';
  btn.textContent = '↻ আবার চেষ্টা করুন';
  btn.addEventListener('click', () => {
    bubble.remove();
    ask(text);
  });
}

async function ask(text) {
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
  let answerRaw = '';
  let failed = false;

  const handle = (ev) => {
    const wasNear = nearBottom();

    switch (ev.type) {
      case 'start':
        sessionId = ev.session_id;
        localStorage.setItem('ec_faq_session_id', sessionId);
        break;

      case 'reasoning':
        think.style.display = '';
        thinkBody.textContent += ev.text;
        thinkBody.scrollTop = thinkBody.scrollHeight;
        break;

      case 'tool_call': {
        collapseThinking();
        chip = el('div', 'tool running', toolsEl);
        el('span', 'tool-name', chip).textContent = '\u{1F527} ' + ev.name;
        let args = ev.arguments || '';
        try {
          args = JSON.stringify(JSON.parse(args));
        } catch (e) {

        }
        el('code', 'tool-args', chip).textContent = args;
        break;
      }

      case 'tool_result': {
        if (!chip) break;
        chip.classList.remove('running');
        const res = el('span', 'tool-res', chip);

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

      case 'done':
        if (!answerRaw.trim()) {
          answerRaw = ev.reply || '(কোনো উত্তর পাওয়া যায়নি)';
          renderAnswer(answerEl, answerRaw);
        }
        break;
    }

    stickToBottom(wasNear);
  };

  function collapseThinking() {
    if (think.style.display === 'none') return;
    think.open = false;
    thinkSummary.textContent = 'চিন্তার ধাপ দেখুন';
  }

  try {
    const res = await fetch('/api/v1/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: sessionId,
        message: text,
        params: readParams(),
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
    if (failed) addRetryButton(bubble, text);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }
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
      await fetch('/api/v1/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId }),
      });
    } catch (e) {

    }
  }
  messagesEl.innerHTML = '';
  greet();
  inputEl.focus();
});

function greet() {
  addRow('bot').textContent =
    'আসসালামু আলাইকুম। এনআইডি বা ভোটার সেবা সম্পর্কে আপনার প্রশ্ন লিখুন।';
}

greet();
