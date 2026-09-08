/*
 * The answer renderer's text half: a small, deliberately partial markdown
 * subset -- the constructs the model actually emits -- turned into HTML.
 * Pure text in, text out; see answer.js for the DOM and math side.
 */

function escapeHtml(text) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function renderInline(text) {
  let out = escapeHtml(text);
  out = out.replace(/`([^`]+)`/g, '<code>$1</code>');
  out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  out = out.replace(/__([^_]+)__/g, '<strong>$1</strong>');
  out = out.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>');
  out = out.replace(/(^|[^_])_([^_\n]+)_(?!_)/g, '$1<em>$2</em>');
  out = out.replace(
    /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
  );
  return out;
}

/*
 * The model routinely writes an enumeration on one line: "1. অ্যাকাউন্ট করুন।
 * ২. লগইন করুন। ৩. ডাউনলোড করুন।" Markdown needs each item on its own line, so
 * all three arrive as a single list item with the later numbers as literal
 * text. Splitting them is safe only with a tight anchor, because a Bengali
 * numeral mid-sentence is also how every fee and date is written.
 *
 * The anchor is a daṛi, then whitespace, then a number followed by a dot or
 * bracket and more whitespace. "২৩০ টাকা" has no dot after the digits and
 * never matches; a sentence that genuinely ends before a numbered step always
 * does. The daṛi is kept -- only the space after it becomes a newline.
 */
const INLINE_ENUMERATION = /(।)\s+(?=[0-9০-৯]+[.)]\s)/g;

export function renderMarkdown(source) {
  const normalised = source
    .replace(/\r\n/g, '\n')
    .replace(INLINE_ENUMERATION, '$1\n');
  const lines = normalised.split('\n');
  const html = [];
  let paragraph = [];
  let list = null;
  let inCode = false;
  let codeLines = [];

  function flushParagraph() {
    if (paragraph.length) {
      html.push('<p>' + renderInline(paragraph.join(' ')) + '</p>');
      paragraph = [];
    }
  }

  function flushList() {
    if (list) {
      html.push('</' + list + '>');
      list = null;
    }
  }

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();

    if (line.trim().startsWith('```')) {
      if (inCode) {
        html.push('<pre><code>' + escapeHtml(codeLines.join('\n')) + '</code></pre>');
        codeLines = [];
        inCode = false;
      } else {
        flushParagraph();
        flushList();
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
      continue;
    }

    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      flushParagraph();
      flushList();
      const level = heading[1].length + 2;
      html.push('<h' + level + '>' + renderInline(heading[2]) + '</h' + level + '>');
      continue;
    }

    const ordered = line.match(/^\s*[0-9০-৯]+[.)]\s+(.*)$/);
    const bulleted = line.match(/^\s*[-*•]\s+(.*)$/);
    if (ordered || bulleted) {
      flushParagraph();
      const tag = ordered ? 'ol' : 'ul';
      if (list !== tag) {
        flushList();
        html.push('<' + tag + '>');
        list = tag;
      }
      html.push('<li>' + renderInline((ordered || bulleted)[1]) + '</li>');
      continue;
    }

    flushList();
    paragraph.push(line);
  }

  flushParagraph();
  flushList();
  if (inCode && codeLines.length) {
    html.push('<pre><code>' + escapeHtml(codeLines.join('\n')) + '</code></pre>');
  }

  return html.join('');
}
