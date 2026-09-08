/*
 * The answer renderer's text half: markdown turned into HTML.
 * Pure text in, text out; see answer.js for the DOM and math side.
 *
 * Block constructs: fenced code, tables, blockquotes, thematic breaks, ATX
 * headings, ordered and bulleted lists (nested, with task items) and
 * paragraphs. Inline: escapes, code spans, images, links, bare URLs, bold,
 * italic, bold-italic, strikethrough and hard breaks.
 *
 * Two things drive the shape of this file rather than a library. The model
 * writes Bengali, so list markers arrive as ০-৯ as often as 0-9. And it writes
 * malformed markdown often enough that being lenient in specific, tested ways
 * matters more than covering every corner of CommonMark.
 */

/*
 * The model routinely writes a list on one line, both numbered --
 * "1. একাউন্ট করুন। ২. লগইন করুন।" -- and bulleted --
 * "*   **নাগরিকত্ব সনদ:** ... সনদ। *   **ইউটিলিটি বিল:** ...". Markdown needs
 * each item on its own line, so the whole run arrives as a single item with
 * every later marker showing as a literal asterisk or numeral.
 *
 * The anchor is tight on purpose: a daṛi, then spaces, then either a number
 * followed by a dot or bracket, or a bullet character, and then more
 * whitespace. Requiring whitespace AFTER the marker is what separates a
 * bullet from emphasis -- "*গুরুত্বপূর্ণ*" has none and is left as italics.
 * "২৩০ টাকা" has no dot after the digits and never matches, nor does
 * "২য় বার ৩৪৫ টাকা". The daṛi is kept; only the space after it becomes a
 * newline.
 */
const INLINE_LIST_ITEM = /(।)[ \t]+(?=(?:[0-9০-৯]+[.)]|[*\-•])[ \t])/g;

const ORDERED = /^(\s*)([0-9০-৯]+)[.)]\s+(.*)$/;
const BULLETED = /^(\s*)[-*+•]\s+(.*)$/;
const TASK = /^\[([ xX])\]\s+(.*)$/;
const HEADING = /^(#{1,6})\s+(.*)$/;
const RULE = /^\s*(?:-{3,}|_{3,}|\*{3,})\s*$/;
const TABLE_DIVIDER = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;

function escapeHtml(text) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/*
 * Code spans and backslash escapes are lifted out before the emphasis rules
 * run and put back afterwards. Without that, `a * b` inside code becomes
 * italics, and an escaped \* is indistinguishable from a real delimiter. The
 * placeholder uses NUL, which cannot occur in a model reply.
 */
function protect(text, store) {
  let out = text.replace(/\\([\\`*_{}[\]()#+\-.!~|>])/g, function (m, ch) {
    store.push(escapeHtml(ch));
    return '\u0000' + (store.length - 1) + '\u0000';
  });
  out = out.replace(/`([^`\n]+)`/g, function (m, code) {
    store.push('<code>' + escapeHtml(code) + '</code>');
    return '\u0000' + (store.length - 1) + '\u0000';
  });
  return out;
}

function restore(text, store) {
  return text.replace(/\u0000(\d+)\u0000/g, function (m, i) {
    return store[Number(i)];
  });
}

function renderInline(text) {
  const store = [];
  let out = protect(text, store);
  out = escapeHtml(out);

  out = out.replace(
    /!\[([^\]]*)\]\((https?:\/\/[^\s)]+)\)/g,
    '<img src="$2" alt="$1" loading="lazy" />'
  );
  out = out.replace(
    /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
  );
  out = out.replace(
    /(^|[\s(])(https?:\/\/[^\s<>")]+)/g,
    '$1<a href="$2" target="_blank" rel="noopener noreferrer">$2</a>'
  );

  out = out.replace(
    /\*\*\*([^*\s](?:[^*]*[^*\s])?)\*\*\*/g,
    '<strong><em>$1</em></strong>'
  );
  out = out.replace(/\*\*([^*\s](?:[^*]*[^*\s])?)\*\*/g, '<strong>$1</strong>');
  out = out.replace(/__([^_\s](?:[^_]*[^_\s])?)__/g, '<strong>$1</strong>');
  // A delimiter has to hug its text, so "* item *" is a bullet, not emphasis.
  out = out.replace(
    /(^|[^*])\*([^*\s\n](?:[^*\n]*[^*\s\n])?)\*(?!\*)/g,
    '$1<em>$2</em>'
  );
  out = out.replace(
    /(^|[^_\w])_([^_\s\n](?:[^_\n]*[^_\s\n])?)_(?!_)/g,
    '$1<em>$2</em>'
  );
  out = out.replace(/~~([^~\s](?:[^~]*[^~\s])?)~~/g, '<del>$1</del>');

  // A paragraph reaches here with its lines still separated by newlines, so
  // that two trailing spaces -- markdown's hard break -- survive the join.
  out = out.replace(/ {2,}\n/g, '<br />');
  out = out.replace(/ {2,}$/, '<br />');
  out = out.replace(/\n/g, ' ');
  return restore(out, store);
}

function splitRow(line) {
  return line
    .replace(/^\s*\|/, '')
    .replace(/\|\s*$/, '')
    .split('|')
    .map(function (cell) { return cell.trim(); });
}

export function renderMarkdown(source) {
  const lines = String(source == null ? '' : source)
    .replace(/\r\n/g, '\n')
    .replace(INLINE_LIST_ITEM, '$1\n')
    .split('\n');

  const html = [];
  let paragraph = [];
  let quote = [];
  const stack = [];
  let inCode = false;
  let codeLines = [];

  function flushParagraph() {
    if (paragraph.length) {
      html.push('<p>' + renderInline(paragraph.join('\n')) + '</p>');
      paragraph = [];
    }
  }

  function flushQuote() {
    if (quote.length) {
      html.push('<blockquote>' + renderMarkdown(quote.join('\n')) + '</blockquote>');
      quote = [];
    }
  }

  function closeLists(depth) {
    while (stack.length > depth) html.push('</' + stack.pop().tag + '>');
  }

  function flushAll() {
    flushParagraph();
    flushQuote();
    closeLists(0);
  }

  for (let i = 0; i < lines.length; i++) {
    const rawLine = lines[i];
    const hardBreak = / {2,}$/.test(rawLine);
    const line = rawLine.replace(/\s+$/, hardBreak ? '  ' : '');

    if (line.trim().startsWith('```')) {
      if (inCode) {
        html.push('<pre><code>' + escapeHtml(codeLines.join('\n')) + '</code></pre>');
        codeLines = [];
        inCode = false;
      } else {
        flushAll();
        inCode = true;
      }
      continue;
    }
    if (inCode) {
      codeLines.push(rawLine);
      continue;
    }

    if (line.trim() === '') {
      flushParagraph();
      flushQuote();
      continue;
    }

    const quoted = line.match(/^\s*>\s?(.*)$/);
    if (quoted) {
      flushParagraph();
      closeLists(0);
      quote.push(quoted[1]);
      continue;
    }
    flushQuote();

    if (RULE.test(line)) {
      flushAll();
      html.push('<hr />');
      continue;
    }

    const heading = line.match(HEADING);
    if (heading) {
      flushAll();
      const level = Math.min(heading[1].length + 2, 6);
      html.push('<h' + level + '>' + renderInline(heading[2]) + '</h' + level + '>');
      continue;
    }

    // A table needs its divider on the next line, which is what separates it
    // from a sentence that merely contains a pipe.
    if (line.includes('|') && TABLE_DIVIDER.test(lines[i + 1] || '')) {
      flushAll();
      const head = splitRow(line);
      const rows = [];
      i += 2;
      while (i < lines.length && lines[i].includes('|') && lines[i].trim() !== '') {
        rows.push(splitRow(lines[i]));
        i++;
      }
      i--;
      html.push(
        '<table><thead><tr>' +
          head.map(function (c) { return '<th>' + renderInline(c) + '</th>'; }).join('') +
          '</tr></thead><tbody>' +
          rows
            .map(function (r) {
              return '<tr>' +
                r.map(function (c) { return '<td>' + renderInline(c) + '</td>'; }).join('') +
                '</tr>';
            })
            .join('') +
          '</tbody></table>'
      );
      continue;
    }

    const ordered = line.match(ORDERED);
    const bulleted = line.match(BULLETED);
    if (ordered || bulleted) {
      flushParagraph();
      const indent = (ordered || bulleted)[1].replace(/\t/g, '  ').length;
      const tag = ordered ? 'ol' : 'ul';
      const body = ordered ? ordered[3] : bulleted[2];

      const depth = Math.floor(indent / 2) + 1;
      while (stack.length > depth) html.push('</' + stack.pop().tag + '>');
      if (stack.length === depth && stack[depth - 1].tag !== tag) {
        html.push('</' + stack.pop().tag + '>');
      }
      while (stack.length < depth) {
        html.push('<' + tag + '>');
        stack.push({ tag: tag, indent: indent });
      }

      const task = body.match(TASK);
      if (task) {
        const done = task[1].toLowerCase() === 'x';
        html.push(
          '<li class="task"><input type="checkbox" disabled' +
            (done ? ' checked' : '') +
            ' /> ' +
            renderInline(task[2]) +
            '</li>'
        );
      } else {
        html.push('<li>' + renderInline(body) + '</li>');
      }
      continue;
    }

    closeLists(0);
    paragraph.push(line);
  }

  flushAll();
  if (inCode && codeLines.length) {
    html.push('<pre><code>' + escapeHtml(codeLines.join('\n')) + '</code></pre>');
  }
  return html.join('');
}
