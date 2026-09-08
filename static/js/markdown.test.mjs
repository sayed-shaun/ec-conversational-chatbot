/*
 * Run with: node static/js/markdown.test.mjs
 *
 * markdown.js is an ES module the browser loads directly, but node treats a
 * bare .js as CommonJS unless a package.json declares otherwise -- and adding
 * one under static/ would change what Vercel builds. So the source is read and
 * imported as a data URL instead, which needs no configuration anywhere.
 */
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('./markdown.js', import.meta.url), 'utf8');
const { renderMarkdown: R } = await import(
  'data:text/javascript;base64,' + Buffer.from(source, 'utf8').toString('base64')
);

let pass = 0, fail = 0;
function t(name, src, expectFn) {
  let html;
  try { html = R(src); } catch (e) { fail++; console.log('THROW ' + name + ' :: ' + e.message); return; }
  const problems = expectFn(html);
  if (problems.length) { fail++; console.log('FAIL  ' + name); problems.forEach(p => console.log('        ' + p)); console.log('        got: ' + html.slice(0, 260)); }
  else { pass++; console.log('ok    ' + name); }
}
const has = (h, ...xs) => xs.filter(x => !h.includes(x)).map(x => 'missing ' + x);
const n = (h, tag) => (h.match(new RegExp('<' + tag + '(?:[ >])', 'g')) || []).length;

console.log('--- inline');
t('bold',            'ফি **২৩০ টাকা** মাত্র।',      h => has(h,'<strong>২৩০ টাকা</strong>'));
t('bold underscore', 'ফি __২৩০__ মাত্র।',            h => has(h,'<strong>২৩০</strong>'));
t('italic',          'এটি *গুরুত্বপূর্ণ* তথ্য।',      h => has(h,'<em>গুরুত্বপূর্ণ</em>'));
t('italic underscore','এটি _জরুরি_ তথ্য।',           h => has(h,'<em>জরুরি</em>'));
t('bold italic',     '***খুব জরুরি*** বিষয়।',        h => has(h,'<strong><em>খুব জরুরি</em></strong>'));
t('strikethrough',   'পুরোনো ~~৫৭০ টাকা~~ নয়।',      h => has(h,'<del>৫৭০ টাকা</del>'));
t('inline code',     'পোর্টাল `services.nidw.gov.bd` দেখুন।', h => has(h,'<code>services.nidw.gov.bd</code>'));
t('code protects *', 'কোড `a * b * c` দেখুন।',        h => h.includes('<em>') ? ['emphasis applied inside code'] : []);
t('escaped asterisk','\\*এটি তারকা নয়\\*',            h => h.includes('<em>') ? ['escape ignored'] : []);
t('link',            '[পোর্টাল](https://services.nidw.gov.bd)', h => has(h,'href="https://services.nidw.gov.bd"','>পোর্টাল</a>'));
t('bare url',        'দেখুন https://services.nidw.gov.bd এখানে।', h => has(h,'<a href="https://services.nidw.gov.bd"'));
t('image',           '![ছবি](https://x.test/a.png)',  h => has(h,'<img src="https://x.test/a.png"','alt="ছবি"'));
t('hard break',      'লাইন এক  \nলাইন দুই',           h => has(h,'<br />'));
t('html escaped',    '<script>alert(1)</script>',     h => h.includes('<script>') ? ['not escaped'] : has(h,'&lt;script&gt;'));

console.log('--- blocks');
t('h1..h3',          '# এক\n## দুই\n### তিন',          h => has(h,'<h3>এক</h3>','<h4>দুই</h4>','<h5>তিন</h5>'));
t('paragraphs',      'এক লাইন।\n\nদুই লাইন।',          h => n(h,'p') === 2 ? [] : ['expected 2 <p>, got ' + n(h,'p')]);
t('thematic break',  'উপরে\n\n---\n\nনিচে',            h => has(h,'<hr />'));
t('blockquote',      '> উদ্ধৃতি এক\n> উদ্ধৃতি দুই',     h => has(h,'<blockquote>','উদ্ধৃতি এক'));
t('fenced code',     '```\nconst a = 1;\n```',        h => has(h,'<pre><code>','const a = 1;'));
t('fence keeps md',  '```\n**not bold**\n```',        h => h.includes('<strong>') ? ['markdown applied inside fence'] : []);

console.log('--- lists');
t('bulleted',        '* এক\n* দুই',                    h => n(h,'li') === 2 && n(h,'ul') === 1 ? [] : ['expected 2 li in 1 ul']);
t('ordered ascii',   '1. এক\n2. দুই',                  h => n(h,'li') === 2 && n(h,'ol') === 1 ? [] : ['expected 2 li in 1 ol']);
t('ordered bengali', '১. এক\n২. দুই',                  h => n(h,'li') === 2 && n(h,'ol') === 1 ? [] : ['expected 2 li in 1 ol']);
t('nested list',     '* বাইরে\n  * ভিতরে\n  * ভিতরে দুই\n* বাইরে দুই',
                     h => n(h,'ul') === 2 && n(h,'li') === 4 ? [] : ['expected 2 ul / 4 li, got ' + n(h,'ul') + '/' + n(h,'li')]);
t('list switch type','* বুলেট\n1. সংখ্যা',              h => n(h,'ul') === 1 && n(h,'ol') === 1 ? [] : ['expected one ul then one ol']);
t('task list',       '- [x] শেষ\n- [ ] বাকি',          h => has(h,'checkbox','checked'));
t('bold in li',      '*   **নোট:** যোগাযোগ করুন।',    h => has(h,'<strong>নোট:</strong>','<li>'));

console.log('--- tables');
t('table',           '| সেবা | ফি |\n|---|---|\n| রি-ইস্যু | ২৩০ |\n| সংশোধন | ৩৪৫ |',
                     h => has(h,'<table>','<th>সেবা</th>','<td>রি-ইস্যু</td>','<td>৩৪৫</td>'));
t('pipe not a table','ফি ২৩০ | ৩৪৫ টাকা।',            h => h.includes('<table>') ? ['prose became a table'] : []);

console.log('--- the reported malformations');
t('inline bullets',  '*   **নাগরিকত্ব সনদ:** সনদ। *   **ইউটিলিটি বিল:** কপি। *   **এনআইডি কপি:** কপি।',
                     h => n(h,'li') === 3 && !h.includes('*') ? [] : ['expected 3 li and no literal *, got ' + n(h,'li')]);
t('inline numbers',  '1. একাউন্ট করুন। ২. লগইন করুন। ৩. ডাউনলোড করুন।',
                     h => n(h,'li') === 3 && !h.includes('*') ? [] : ['expected 3 li, got ' + n(h,'li')]);
t('bullet not italic','*   **ভোট:** করুন।',            h => h.includes('<em>') ? ['bullet italicised'] : []);

console.log('--- group headings');
t('bold-only item becomes a heading',
  '*   **৩ বছর পর্যন্ত সংশোধনের জন্য:**\n*   অনলাইন জন্ম নিবন্ধন সনদ।\n*   পাসপোর্ট।\n*   **৩ বছর এর বেশি সংশোধনের ক্ষেত্রে:**\n*   স্বামীর এনআইডি।\n*   ওয়ারিশান সনদ।',
  h => {
    const groups = (h.match(/class="list-group"/g) || []).length;
    const problems = [];
    if (groups !== 2) problems.push('expected 2 group headings, got ' + groups);
    if (n(h,'ul') !== 2) problems.push('expected 2 <ul>, got ' + n(h,'ul'));
    if (n(h,'li') !== 4) problems.push('expected 4 <li>, got ' + n(h,'li'));
    if (h.includes('<ul></ul>')) problems.push('empty <ul> emitted');
    return problems;
  });
t('label WITH a body stays a bullet',
  '*   **নাগরিকত্ব সনদ:** চেয়ারম্যানের সনদ।',
  h => (n(h,'li') === 1 && h.includes('<strong>নাগরিকত্ব সনদ:</strong>') && !h.includes('list-group'))
        ? [] : ['should remain one <li> with a bold label']);
t('bold item without a colon stays a bullet',
  '*   **শুধু গাঢ় লেখা**\n*   পরের আইটেম',
  h => (n(h,'li') === 2 && !h.includes('list-group')) ? [] : ['no colon, so not a heading']);
t('nested bold-only item stays a bullet',
  '*   বাইরের\n  *   **ভিতরের গাঢ়:**',
  h => h.includes('list-group') ? ['nested item wrongly promoted'] : []);

console.log('--- must not change');
t('fee prose',       'ফি প্রথমবার ২৩০ টাকা। ২য় বার ৩৪৫ টাকা। পরবর্তীতে ৫৭৫ টাকা।',
                     h => n(h,'li') === 0 && n(h,'p') === 1 ? [] : ['should stay one <p>']);
t('helpline',        'তথ্য পাওয়া যায়নি। অনুগ্রহ করে ১০৫ নম্বরে কল করুন।',
                     h => n(h,'p') === 1 && n(h,'li') === 0 ? [] : ['should stay one <p>']);
t('well-formed list','প্রয়োজন:\n\n*   **সনদ:** ক।\n*   **বিল:** খ।\n*   **কপি:** গ।',
                     h => n(h,'li') === 3 ? [] : ['expected 3 li, got ' + n(h,'li')]);
t('empty input',     '',                              h => h === '' ? [] : ['expected empty string']);
t('null input',      null,                            h => h === '' ? [] : ['expected empty string']);

console.log(`\n${pass} passed, ${fail} failed`);
if (fail) process.exit(1);
