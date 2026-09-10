/* Small DOM and formatting helpers shared across the UI. */

export function el(tag, cls, parent) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (parent) parent.appendChild(node);
  return node;
}

const BENGALI_DIGITS = ['০', '১', '২', '৩', '৪', '৫', '৬', '৭', '৮', '৯'];

function toBengaliDigits(str) {
  return String(str).replace(/[0-9]/g, (d) => BENGALI_DIGITS[+d]);
}

export function formatSeconds(ms) {
  return toBengaliDigits((ms / 1000).toFixed(1));
}
