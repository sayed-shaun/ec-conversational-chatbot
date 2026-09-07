/*
 * Preparing reply text for the voice: markdown stripped, and digits spelled
 * out as words.
 */

/*
 * Number/domain-to-words conversion for speech.
 *
 * The LLM is deliberately left free to write digits (asking it to spell
 * numbers out itself was tried and reverted -- it reliably gets the VALUE
 * right with digits, but occasionally hallucinates non-Bangla fragments
 * (e.g. Cyrillic) when asked to spell tricky numbers like 115 as words).
 * Converting digits to words here instead is deterministic: same input,
 * same output, no model involved, so there's nothing for it to get wrong.
 */

const BN_DIGIT_MAP = { '০': '0', '১': '1', '২': '2', '৩': '3', '৪': '4', '৫': '5', '৬': '6', '৭': '7', '৮': '8', '৯': '9' };
const normalizeDigits = (s) => s.replace(/[০-৯]/g, (d) => BN_DIGIT_MAP[d]);

// Bangla has a distinct word for every number 0-99 (not composed from
// tens+ones like English), so this has to be a full lookup table.
const BN_TWO_DIGIT = [
  'শূন্য', 'এক', 'দুই', 'তিন', 'চার', 'পাঁচ', 'ছয়', 'সাত', 'আট', 'নয়', 'দশ',
  'এগারো', 'বারো', 'তেরো', 'চৌদ্দ', 'পনেরো', 'ষোলো', 'সতেরো', 'আঠারো', 'উনিশ', 'বিশ',
  'একুশ', 'বাইশ', 'তেইশ', 'চব্বিশ', 'পঁচিশ', 'ছাব্বিশ', 'সাতাশ', 'আটাশ', 'ঊনত্রিশ', 'ত্রিশ',
  'একত্রিশ', 'বত্রিশ', 'তেত্রিশ', 'চৌত্রিশ', 'পঁয়ত্রিশ', 'ছত্রিশ', 'সাঁইত্রিশ', 'আটত্রিশ', 'ঊনচল্লিশ', 'চল্লিশ',
  'একচল্লিশ', 'বিয়াল্লিশ', 'তেতাল্লিশ', 'চুয়াল্লিশ', 'পঁয়তাল্লিশ', 'ছেচল্লিশ', 'সাতচল্লিশ', 'আটচল্লিশ', 'ঊনপঞ্চাশ', 'পঞ্চাশ',
  'একান্ন', 'বাহান্ন', 'তিপ্পান্ন', 'চুয়ান্ন', 'পঞ্চান্ন', 'ছাপ্পান্ন', 'সাতান্ন', 'আটান্ন', 'ঊনষাট', 'ষাট',
  'একষট্টি', 'বাষট্টি', 'তেষট্টি', 'চৌষট্টি', 'পঁয়ষট্টি', 'ছেষট্টি', 'সাতষট্টি', 'আটষট্টি', 'ঊনসত্তর', 'সত্তর',
  'একাত্তর', 'বাহাত্তর', 'তিয়াত্তর', 'চুয়াত্তর', 'পঁচাত্তর', 'ছিয়াত্তর', 'সাতাত্তর', 'আটাত্তর', 'ঊনআশি', 'আশি',
  'একাশি', 'বিরাশি', 'তিরাশি', 'চুরাশি', 'পঁচাশি', 'ছিয়াশি', 'সাতাশি', 'আটাশি', 'ঊননব্বই', 'নব্বই',
  'একানব্বই', 'বিরানব্বই', 'তিরানব্বই', 'চুরানব্বই', 'পঁচানব্বই', 'ছিয়ানব্বই', 'সাতানব্বই', 'আটানব্বই', 'নিরানব্বই',
];

function banglaHundredsToWords(n) {
  const h = Math.floor(n / 100);
  const r = n % 100;
  let out = '';
  if (h > 0) out += BN_TWO_DIGIT[h] + 'শ' + (r > 0 ? ' ' : '');
  if (r > 0) out += BN_TWO_DIGIT[r];
  return out.trim();
}

// Bangla groups digits as crore/lakh/thousand/hundred (2-2-2-3), not the
// Western 3-3-3 (million/billion) grouping.
function numberToBanglaWords(n) {
  if (n === 0) return 'শূন্য';
  if (n < 0) return 'ঋণাত্মক ' + numberToBanglaWords(-n);
  const parts = [];
  const crore = Math.floor(n / 1e7); n %= 1e7;
  const lakh = Math.floor(n / 1e5); n %= 1e5;
  const thousand = Math.floor(n / 1e3); n %= 1e3;
  if (crore) parts.push(BN_TWO_DIGIT[crore] + ' কোটি');
  if (lakh) parts.push(BN_TWO_DIGIT[lakh] + ' লক্ষ');
  if (thousand) parts.push(BN_TWO_DIGIT[thousand] + ' হাজার');
  if (n) parts.push(banglaHundredsToWords(n));
  return parts.join(' ').trim();
}

const BN_ORDINAL = [
  '', 'প্রথম', 'দ্বিতীয়', 'তৃতীয়', 'চতুর্থ', 'পঞ্চম', 'ষষ্ঠ', 'সপ্তম', 'অষ্টম', 'নবম', 'দশম',
  'একাদশ', 'দ্বাদশ', 'ত্রয়োদশ', 'চতুর্দশ', 'পঞ্চদশ', 'ষোড়শ', 'সপ্তদশ', 'অষ্টাদশ', 'ঊনবিংশ', 'বিংশ',
];
const banglaOrdinalWord = (n) => (n >= 1 && n < BN_ORDINAL.length ? BN_ORDINAL[n] : numberToBanglaWords(n) + 'তম');

// Days of the month: 1st-4th are irregular idioms, 5th+ is regular
// (cardinal word + whichever suffix -ই/-শে the source text already used).
const BN_DATE_ORDINAL_SPECIAL = { 1: 'পয়লা', 2: 'দোসরা', 3: 'তেসরা', 4: 'চৌঠা' };
function banglaDateOrdinalWord(n, suffix) {
  if (BN_DATE_ORDINAL_SPECIAL[n]) return BN_DATE_ORDINAL_SPECIAL[n];
  const word = numberToBanglaWords(n);
  // e.g. পঁচিশ + শে would double the শ (পঁচিশশে) -- the real word elides
  // it to পঁচিশে, same for ত্রিশে/বিশে etc.
  if (suffix === 'শে' && word.endsWith('শ')) return word + 'ে';
  return word + suffix;
}

const EN_ORDINAL = [
  '', 'first', 'second', 'third', 'fourth', 'fifth', 'sixth', 'seventh', 'eighth', 'ninth', 'tenth',
  'eleventh', 'twelfth', 'thirteenth', 'fourteenth', 'fifteenth', 'sixteenth', 'seventeenth', 'eighteenth', 'nineteenth', 'twentieth',
];
const englishOrdinalWord = (n) => (n >= 1 && n < EN_ORDINAL.length ? EN_ORDINAL[n] : n + 'th');

// Long digit runs (NID numbers, mobile numbers) or anything near "নম্বর
// /কল/হেল্পলাইন" read as a magnitude would be nonsense -- read digit by
// digit instead, same convention as a phone number in any language.
function digitByDigit(digits) {
  return normalizeDigits(digits).split('').map((d) => BN_TWO_DIGIT[+d]).join(' ');
}

const EN_DIGIT_WORDS = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine'];
const digitByDigitEnglish = (digits) => digits.split('').map((d) => EN_DIGIT_WORDS[+d]).join(' ');

function convertNumbersForSpeech(text) {
  let out = text;

  // Known domain the FAQ data repeats often; give it a clean phonetic
  // reading instead of leaving Latin letters for the Bangla voice model.
  out = out.replace(/services\.nidw\.gov\.bd/gi, 'সার্ভিসেস ডট এনআইডিডাব্লিউ ডট গভ ডট বিডি');
  // Any other bare domain-looking token: break it on the dots so it isn't
  // read as one long run-on word.
  out = out.replace(/\b[a-zA-Z][a-zA-Z0-9-]*(?:\.[a-zA-Z]{2,})+\b/g, (m) => m.split('.').join(' ডট '));

  // Date ordinals: digits directly followed by -লা/-রা/-শে/-ঠা/-ই.
  out = out.replace(/([০-৯]+|\d+)(লা|রা|শে|ঠা|ই)/g, (m, num, suffix) =>
    banglaDateOrdinalWord(parseInt(normalizeDigits(num), 10), suffix)
  );
  // General ordinals: ১ম, ২য়, ৩য়, ৪র্থ, ৫ম, ৬ষ্ঠ, ...
  out = out.replace(/([০-৯]+|\d+)(ম|য়|র্থ|ষ্ঠ)/g, (m, num) =>
    banglaOrdinalWord(parseInt(normalizeDigits(num), 10))
  );
  // English ordinals: 1st, 2nd, 3rd, 4th, ...
  out = out.replace(/\b(\d+)(st|nd|rd|th)\b/gi, (m, num) => englishOrdinalWord(parseInt(num, 10)));

  // Helpline/ID-style numbers: long runs, or short runs next to a word
  // like "নম্বর"/"কল"/"call"/"number" -- read digit by digit (like a real
  // phone number in any language), not as one big magnitude.
  out = out.replace(/([০-৯]{6,}|\d{6,})/g, (m) => digitByDigit(m));
  out = out.replace(/(নম্বর|নম্বরে|নম্বরটি|কল করে|কল করুন|হেল্পলাইন|হটলাইন)\s*([০-৯]+|\d+)/g, (m, label, num) =>
    label + ' ' + digitByDigit(num)
  );
  out = out.replace(/([০-৯]+|\d+)\s*(নম্বরে|নম্বরটি|নম্বর)/g, (m, num, label) => digitByDigit(num) + ' ' + label);
  out = out.replace(/\b(call|number|helpline|hotline|dial)\b\s*:?\s*([0-9]+)/gi, (m, label, num) =>
    label + ' ' + digitByDigitEnglish(num)
  );
  out = out.replace(/\b([0-9]+)\s*(?=is the (?:number|helpline|hotline))/gi, (m, num) => digitByDigitEnglish(num) + ' ');

  // Whatever plain digit runs remain: read as a normal magnitude (fees,
  // ages, years, quantities).
  out = out.replace(/[০-৯]+|\d+/g, (m) => numberToBanglaWords(parseInt(normalizeDigits(m), 10)));

  return out;
}

// Strip markdown noise before handing text to TTS, so the voice doesn't
// read out asterisks, hashes, or link syntax.
export function stripMarkdownForSpeech(text) {
  const plain = text
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/[#*_>~]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
  return convertNumbersForSpeech(plain);
}

