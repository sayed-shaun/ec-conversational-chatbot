/*
 * Speech recognition: turning a browser recording into a transcript.
 */

import { API_BASE } from './config.js';

/*
 * Measured against this very ASR service: a 0.9s "হ্যালো" transcribes
 * correctly with no padding, and returns an empty string once 2.5s of
 * trailing silence is appended -- and the shortest word tested, "হ্যাঁ",
 * already fails at 1.0s. Its segmenter evidently weighs the speech-to-
 * silence ratio, so the ~1s hangover listen() must leave on the end of
 * every clip (it cannot know a phrase is over until silence has run for a
 * beat) is exactly what breaks one-word turns. Long sentences survive
 * because they carry enough speech to transcribe regardless.
 *
 * So the padding is cut here, between recording and upload: decode the
 * clip, keep only the parts that are actually speech, and re-encode
 * those as 16 kHz mono WAV -- the rate and format acoustic models
 * expect, which also drops the Opus round trip and shrinks the upload.
 */

const ASR_SAMPLE_RATE = 16000;

// One lazily-created context, reused for every decode. Browsers cap how
// many AudioContexts may exist at once (Chrome allows about six), and
// close() resolves asynchronously -- so building one per utterance risks
// hitting the cap partway through a conversation. Deliberately not the mic's
// own context: closing that would end the recording.
let decodeCtx = null;

async function decodeToMono(blob) {
  if (!decodeCtx) {
    decodeCtx = new (window.AudioContext || window.webkitAudioContext)();
  }
  const ctx = decodeCtx;
  {
    const buf = await ctx.decodeAudioData(await blob.arrayBuffer());
    const chans = [];
    for (let c = 0; c < buf.numberOfChannels; c++) chans.push(buf.getChannelData(c));
    if (chans.length === 1) return { samples: chans[0], sampleRate: buf.sampleRate };
    // Average the channels rather than taking the first: a stereo capture
    // with the voice on one side would otherwise arrive at half level.
    const mono = new Float32Array(buf.length);
    for (let i = 0; i < buf.length; i++) {
      let sum = 0;
      for (let c = 0; c < chans.length; c++) sum += chans[c][i];
      mono[i] = sum / chans.length;
    }
    return { samples: mono, sampleRate: buf.sampleRate };
  }
}

/*
 * Returns just the speech, with silence removed -- or null if the clip holds
 * none.
 *
 * Measured against real recordings from this page: the ASR returns a
 * transcript whenever speech occupies roughly a fifth of the clip or more,
 * and an empty string below that. A 6.9s clip at 19% speech transcribed; a
 * 9.4s clip at 13% and a 34.6s one at 11% both came back empty. The same
 * 9.4s clip, compacted by this function to 1.24s, transcribes correctly.
 *
 * Trimming only the outer ends is not enough, which is what the earlier
 * version got wrong: one stray noise blip near the end keeps the whole span
 * between it and the speech, and density stays just as low. So interior
 * silence is dropped too, which bounds density from below no matter how long
 * the turn ran or what the VAD did.
 */
function extractSpeech(samples, sampleRate) {
  // Window-based rather than per-sample: one sample says nothing about
  // whether speech is present, and a zero crossing mid-vowel would cut the
  // word in half.
  const win = Math.max(1, Math.round(sampleRate * 0.02));
  const energies = [];
  for (let i = 0; i < samples.length; i += win) {
    const end = Math.min(i + win, samples.length);
    let sum = 0;
    for (let j = i; j < end; j++) sum += samples[j] * samples[j];
    energies.push(Math.sqrt(sum / (end - i)));
  }
  if (!energies.length) return null;

  const sorted = Float64Array.from(energies).sort();
  const peak = sorted[sorted.length - 1];
  if (peak <= 0) return null;
  // The clip's own noise level, as a low percentile rather than the minimum
  // (a single near-zero window would drag the estimate to nothing).
  const noise = sorted[Math.floor(sorted.length * 0.2)];
  // Both terms are needed. Peak-relative alone sets the bar under the noise
  // when speech is loud -- a 0.22 peak gives 0.013, below a 0.009 noise
  // floor, so noise counts as speech. Noise-relative alone drifts up with a
  // loud room and starts eating quiet speech.
  const bar = Math.max(peak * 0.10, noise * 3, 1e-4);

  const margin = Math.max(1, Math.round(sampleRate * 0.15 / win));
  const bridge = Math.max(1, Math.round(sampleRate * 0.30 / win));
  const keep = new Uint8Array(energies.length);
  for (let i = 0; i < energies.length; i++) {
    if (energies[i] <= bar) continue;
    // Margin either side: cutting flush against a loud window clips a soft
    // onset and the decay of a final consonant, both of which the model
    // needs to identify the word.
    const from = Math.max(0, i - margin);
    const to = Math.min(energies.length - 1, i + margin);
    for (let j = from; j <= to; j++) keep[j] = 1;
  }

  // Bridge short internal gaps, so a natural pause between words does not
  // become a splice the model hears as two unrelated fragments. Only gaps
  // BETWEEN speech are bridged; leading and trailing silence still goes.
  for (let i = 0; i < keep.length; ) {
    if (keep[i]) { i++; continue; }
    let j = i;
    while (j < keep.length && !keep[j]) j++;
    if (i > 0 && j < keep.length && j - i <= bridge) {
      for (let k = i; k < j; k++) keep[k] = 1;
    }
    i = j;
  }

  let kept = 0;
  for (let i = 0; i < keep.length; i++) if (keep[i]) kept++;
  if (!kept) return null;

  const out = new Float32Array(kept * win);
  let at = 0;
  for (let i = 0; i < keep.length; i++) {
    if (!keep[i]) continue;
    const from = i * win;
    const to = Math.min(from + win, samples.length);
    for (let j = from; j < to; j++) out[at++] = samples[j];
  }
  return out.subarray(0, at);
}

function downsample(samples, from, to) {
  if (from <= to) return { samples: samples, sampleRate: from };
  const ratio = from / to;
  const outLen = Math.floor(samples.length / ratio);
  const out = new Float32Array(outLen);
  // Average each output sample's whole input span instead of point-sampling
  // it. Dropping 48 kHz to 16 kHz by picking every third sample folds
  // everything above 8 kHz back down as aliasing noise -- squarely into the
  // band the model is listening to.
  for (let i = 0; i < outLen; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(Math.floor((i + 1) * ratio), samples.length);
    let sum = 0;
    for (let j = start; j < end; j++) sum += samples[j];
    out[i] = end > start ? sum / (end - start) : 0;
  }
  return { samples: out, sampleRate: to };
}

function encodeWav(samples, sampleRate) {
  const bytes = samples.length * 2;
  const view = new DataView(new ArrayBuffer(44 + bytes));
  const ascii = (off, str) => {
    for (let i = 0; i < str.length; i++) view.setUint8(off + i, str.charCodeAt(i));
  };
  ascii(0, 'RIFF');
  view.setUint32(4, 36 + bytes, true);
  ascii(8, 'WAVEfmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);                 // PCM
  view.setUint16(22, 1, true);                 // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);    // byte rate
  view.setUint16(32, 2, true);                 // block align
  view.setUint16(34, 16, true);                // bits per sample
  ascii(36, 'data');
  view.setUint32(40, bytes, true);
  let off = 44;
  for (let i = 0; i < samples.length; i++, off += 2) {
    const v = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(off, v < 0 ? v * 0x8000 : v * 0x7fff, true);
  }
  return new Blob([view.buffer], { type: 'audio/wav' });
}

// Returns a trimmed 16 kHz mono WAV, or null if the clip held no speech.
export async function prepareForAsr(blob) {
  const decoded = await decodeToMono(blob);
  const speech = extractSpeech(decoded.samples, decoded.sampleRate);
  if (!speech || !speech.length) return null;
  const out = downsample(speech, decoded.sampleRate, ASR_SAMPLE_RATE);
  return encodeWav(out.samples, out.sampleRate);
}

export async function transcribe(blob) {
  /*
   * Goes through our own backend (POST /api/v1/asr), which forwards to the
   * speech service's OpenAI-compatible /v1/audio/transcriptions. Same
   * reasoning as sendTts() below: one origin for the browser, and the model
   * host stays a server-side detail rather than something the page knows.
   */
  const form = new FormData();
  const type = blob.type || '';
  const ext = type.includes('wav') ? 'wav' : type.includes('mp4') ? 'mp4' : 'webm';
  form.append('file', blob, 'recording.' + ext);

  const res = await fetch(API_BASE + '/api/v1/asr', {
    method: 'POST',
    headers: { 'ngrok-skip-browser-warning': 'true' },
    body: form,
  });
  if (!res.ok) throw new Error('HTTP ' + res.status);

  const data = await res.json();
  return (data.text || '').trim();
}
