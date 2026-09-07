/*
 * Text to speech: streaming playback, and the buffered fallback.
 */

import { API_BASE } from './config.js';
import { stripMarkdownForSpeech } from './speech-text.js';

// Generous because streaming removes the latency cost of a longer reply;
// still bounded so a runaway generation cannot queue minutes of audio.
const TTS_MAX_CHARS = 3000;

/*
 * Streaming speech playback.
 *
 * The service can stream, and the difference dominates how quickly the bot
 * answers: for one measured 468-character reply the first audio byte
 * arrives after 2.2s streamed against 12.6s buffered. It generates about
 * 2.7x faster than realtime, so playback started at the first chunk never
 * catches up with synthesis.
 *
 * Streaming has to be raw PCM (a WAV header must declare a length nothing
 * knows until the last clause is done), and an <audio> element cannot play
 * headerless samples. So this schedules the chunks through Web Audio
 * instead: decode each s16le block to Float32, and queue it to start
 * exactly where the previous one ended.
 */
function createSpeechStream(ctx, sampleRate, channels) {
  // Where the next chunk begins on the context clock. Scheduling against
  // this running cursor rather than "now" is what makes playback gapless:
  // the buffers abut sample-exactly, instead of drifting by however long
  // each chunk took to arrive.
  let cursor = 0;
  let leftover = new Uint8Array(0);
  const sources = [];
  let stopped = false;

  return {
    // Returns the time at which everything queued so far finishes.
    get endsAt() { return cursor; },

    push(bytes) {
      if (stopped) return;
      // A chunk boundary can fall mid-sample, so carry the odd trailing
      // byte (or odd frame, for multichannel) into the next chunk rather
      // than dropping it -- dropping one byte would swap the high and low
      // halves of every sample after it, turning the rest into noise.
      const frame = 2 * channels;
      const joined = new Uint8Array(leftover.length + bytes.length);
      joined.set(leftover);
      joined.set(bytes, leftover.length);
      const usable = joined.length - (joined.length % frame);
      leftover = joined.subarray(usable);
      if (!usable) return;

      const pcm = new DataView(joined.buffer, joined.byteOffset, usable);
      const frames = usable / frame;
      const buf = ctx.createBuffer(channels, frames, sampleRate);
      for (let c = 0; c < channels; c++) {
        const out = buf.getChannelData(c);
        for (let i = 0; i < frames; i++) {
          out[i] = pcm.getInt16((i * channels + c) * 2, true) / 32768;
        }
      }

      const src = ctx.createBufferSource();
      src.buffer = buf;
      src.connect(ctx.destination);
      // A late first chunk (or a stall) leaves the cursor in the past;
      // restart from now, otherwise the audio would be scheduled for a
      // moment that has already gone and play all at once.
      const startAt = Math.max(cursor, ctx.currentTime);
      src.start(startAt);
      cursor = startAt + buf.duration;
      sources.push(src);
      src.onended = () => {
        const at = sources.indexOf(src);
        if (at >= 0) sources.splice(at, 1);
      };
    },

    stop() {
      stopped = true;
      sources.forEach((src) => {
        try { src.stop(); } catch (e) {}
      });
      sources.length = 0;
      // Collapse the queue as well as silencing it, so a caller waiting on
      // endsAt stops waiting for audio that will now never play.
      cursor = 0;
    },
  };
}

/*
 * Streams one reply and plays it. Resolves when the audio finishes, and
 * rejects if the stream could not be started at all -- so the caller can
 * fall back to the buffered path. `onStart` fires at the first audio, which
 * is when the orb should say "speaking" rather than "thinking".
 */
export async function speakStreaming(text, ctx, onStart, registerStop, meta) {
  const res = await fetch(API_BASE + '/api/v1/tts', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'ngrok-skip-browser-warning': 'true',
    },
    body: JSON.stringify({
      input: stripMarkdownForSpeech(text).slice(0, TTS_MAX_CHARS),
      voice: 'Aditi',
      stream: true,
      turn_id: (meta && meta.turnId) || null,
      session_id: (meta && meta.sessionId) || null,
    }),
  });
  if (!res.ok || !res.body) throw new Error('HTTP ' + res.status);

  // Read the format off the response rather than assuming it, so a change
  // of voice or model upstream cannot silently detune playback.
  const rate = parseInt(res.headers.get('x-audio-sample-rate'), 10) || 44100;
  const channels = parseInt(res.headers.get('x-audio-channels'), 10) || 1;

  const stream = createSpeechStream(ctx, rate, channels);
  registerStop(() => stream.stop());

  const reader = res.body.getReader();
  let started = false;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    if (!value || !value.length) continue;
    stream.push(value);
    if (!started) {
      started = true;
      onStart();
    }
  }
  if (!started) throw new Error('empty TTS stream');

  // Wait out whatever is still queued. The cursor is on the context clock,
  // so this is the real remaining audio, not an estimate.
  const remaining = stream.endsAt - ctx.currentTime;
  if (remaining > 0) {
    await new Promise((resolve) => setTimeout(resolve, remaining * 1000));
  }
}

export async function synthesizeSpeech(text, meta) {
  /*
   * Goes through our own backend (POST /api/v1/tts), not the TTS service's
   * /v1/audio/speech directly -- that service has no CORS support, so a UI
   * hosted on a different origin (e.g. Vercel) would have the browser
   * block the request. Our backend forwards it and inherits its own
   * CORSMiddleware instead.
   */
  const res = await fetch(API_BASE + '/api/v1/tts', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'ngrok-skip-browser-warning': 'true',
    },
    body: JSON.stringify({
      input: stripMarkdownForSpeech(text).slice(0, TTS_MAX_CHARS),
      voice: 'Aditi',
      response_format: 'wav',
      turn_id: (meta && meta.turnId) || null,
      session_id: (meta && meta.sessionId) || null,
    }),
  });
  if (!res.ok) throw new Error('HTTP ' + res.status);
  const blob = await res.blob();
  if (!blob.size) throw new Error('empty TTS response');
  return URL.createObjectURL(blob);
}
