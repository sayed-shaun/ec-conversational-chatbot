/*
 * Text to speech: streaming playback, and the buffered fallback.
 *
 * The reply is sent as written. Making it speakable -- markdown out, digits
 * into Bangla words, initialisms respelled -- happens in the /tts route
 * (src/chatbot/transform.py), so every caller gets it, not just this page.
 */

import { API_BASE } from './config.js';

/*
 * A noise gate for one stream. The service's output has a flat hiss of about
 * -40 dBFS in every pause and between words, while speech sits well above it
 * (soft word endings still reach about -30 dBFS). Filters cannot remove it, since
 * it overlaps the voice, so the pauses are turned down instead: the gate closes
 * to FLOOR when a 10 ms block and the one after it are both quiet, and opens when
 * either is loud. Two thresholds (open higher than close) and a hold keep it from
 * chattering on soft syllables, and the gain moves smoothly so no step is heard.
 * State is carried across chunks because a word can span them.
 */
export function createNoiseGate(sampleRate) {
  const OPEN = 0.022;
  const CLOSE = 0.015;
  const FLOOR = 0.2;
  const HOLD = Math.round(0.06 * sampleRate);
  const block = Math.round(0.01 * sampleRate);
  const attack = 1 - Math.exp(-1 / (0.003 * sampleRate));
  const release = 1 - Math.exp(-1 / (0.05 * sampleRate));
  let gain = 1;
  let open = true;
  let hold = HOLD;

  const rms = (data, from, to) => {
    let sum = 0;
    for (let i = from; i < to; i++) sum += data[i] * data[i];
    return Math.sqrt(sum / Math.max(1, to - from));
  };

  // Gates one chunk of mono samples in place.
  return function gate(data) {
    const n = data.length;
    for (let b = 0; b < n; b += block) {
      const e = Math.min(n, b + block);
      const level = Math.max(rms(data, b, e), e < n ? rms(data, e, Math.min(n, e + block)) : 0);
      if (level > (open ? CLOSE : OPEN)) {
        open = true;
        hold = HOLD;
      } else if (open) {
        hold -= e - b;
        if (hold <= 0) open = false;
      }
      const target = open ? 1 : FLOOR;
      for (let i = b; i < e; i++) {
        gain += (target - gain) * (target > gain ? attack : release);
        data[i] *= gain;
      }
    }
  };
}

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
  const gate = channels === 1 ? createNoiseGate(sampleRate) : null;
  const sources = [];
  let stopped = false;

  // Everything plays through one chain: a fade gain, two filters, a compressor and
  // a make-up gain.
  // The fade ramps the reply in over FADE seconds (and out in finish()), because
  // the samples do not start or end at zero, which clicks.
  // The service's output carries a flat hiss from 300 Hz up past 16 kHz and a rumble
  // under 100 Hz, while the voice has almost nothing above 8 kHz, so a high-pass
  // and a low-pass take away the noise that sits outside the voice.
  // The service also peak-normalises each reply, so one hard consonant sets the
  // level; the compressor evens loud and soft words out. It is kept mild because
  // its make-up gain raises the hiss between words along with the voice.
  const FADE = 0.015;
  const fade = ctx.createGain();
  const highpass = ctx.createBiquadFilter();
  highpass.type = 'highpass';
  highpass.frequency.value = 90;
  const lowpass = ctx.createBiquadFilter();
  lowpass.type = 'lowpass';
  lowpass.frequency.value = 8500;
  const compressor = ctx.createDynamicsCompressor();
  compressor.threshold.value = -20;
  compressor.knee.value = 12;
  compressor.ratio.value = 2;
  compressor.attack.value = 0.005;
  compressor.release.value = 0.15;
  const makeup = ctx.createGain();
  makeup.gain.value = 1.4;
  fade.connect(highpass);
  highpass.connect(lowpass);
  lowpass.connect(compressor);
  compressor.connect(makeup);
  makeup.connect(ctx.destination);
  let faded = false;

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
        if (gate) gate(out);
      }

      const src = ctx.createBufferSource();
      src.buffer = buf;
      src.connect(fade);
      // A late first chunk (or a stall) leaves the cursor in the past;
      // restart from now, otherwise the audio would be scheduled for a
      // moment that has already gone and play all at once.
      const startAt = Math.max(cursor, ctx.currentTime);
      if (!faded) {
        faded = true;
        fade.gain.setValueAtTime(0, startAt);
        fade.gain.linearRampToValueAtTime(1, startAt + FADE);
      }
      src.start(startAt);
      cursor = startAt + buf.duration;
      sources.push(src);
      src.onended = () => {
        const at = sources.indexOf(src);
        if (at >= 0) sources.splice(at, 1);
      };
    },

    // Called once the last chunk is queued: ramp to silence over the end of the
    // audio so it does not stop on a non-zero sample.
    finish() {
      if (stopped || !faded) return;
      const end = Math.max(cursor, ctx.currentTime + FADE);
      fade.gain.setValueAtTime(1, end - FADE);
      fade.gain.linearRampToValueAtTime(0, end);
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
    },
    body: JSON.stringify({
      input: text,
      voice: 'Aditi',
      stream: true,
      turn_id: (meta && meta.turnId) || null,
      session_id: (meta && meta.sessionId) || null,
      tag: (meta && meta.tag) || '',
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
  stream.finish();

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
   * hosted on a different origin would have the browser
   * block the request. Our backend forwards it and inherits its own
   * CORSMiddleware instead.
   */
  const res = await fetch(API_BASE + '/api/v1/tts', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      input: text,
      voice: 'Aditi',
      response_format: 'wav',
      turn_id: (meta && meta.turnId) || null,
      session_id: (meta && meta.sessionId) || null,
      tag: (meta && meta.tag) || '',
    }),
  });
  if (!res.ok) throw new Error('HTTP ' + res.status);
  const blob = await res.blob();
  if (!blob.size) throw new Error('empty TTS response');
  return URL.createObjectURL(blob);
}
