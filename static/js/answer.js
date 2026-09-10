/*
 * The answer renderer's DOM half: markdown to HTML, then KaTeX over the
 * result. renderMathInElement is a global from the KaTeX auto-render script
 * loaded in index.html.
 */

import { renderMarkdown } from './markdown.js';

function renderMath(container) {
  renderMathInElement(container, {
    delimiters: [
      { left: '$$', right: '$$', display: true },
      { left: '\\[', right: '\\]', display: true },
      { left: '$', right: '$', display: false },
      { left: '\\(', right: '\\)', display: false },
    ],
    throwOnError: false,
  });
}

export function renderAnswer(answerEl, raw) {
  answerEl.innerHTML = renderMarkdown(raw);
  renderMath(answerEl);
}
