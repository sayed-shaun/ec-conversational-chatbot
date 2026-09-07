/*
 * A ChatGPT-style full-screen voice mode: tapping the mic button opens an
 * overlay that listens continuously, auto-detects when the user stops
 * talking (via a Web Audio analyser, not a manual stop button), sends the
 * transcript through the normal chat pipeline, then speaks the reply back
 * via TTS and starts listening again -- a hands-free loop until closed.
 */

import {
  voiceOverlay, voiceOrb, voiceStatus, voiceDebug, voiceTranscript,
  voiceMuteBtn, voiceCloseBtn, micBtn,
} from './elements.js';
import { addUserMessage } from './transcript.js';
import { ask } from './chat.js';
import { prepareForAsr, transcribe } from './asr.js';
import { speakStreaming, synthesizeSpeech } from './tts.js';

const VOICE_DEBUG = new URLSearchParams(location.search).has('vdebug');

const VoiceMode = {
  active: false,
  muted: false,
  stream: null,
  audioCtx: null,
  analyser: null,
  levelRaf: null,
  recorder: null,
  chunks: [],
  silenceTimer: null,
  maxDurationTimer: null,
  speechStarted: false,
  // Room noise level, in the same RMS units as the analyser reads.
  // Lives on the object, not inside listen(), so it carries across
  // turns instead of re-learning the room from scratch each time.
  noiseFloor: 0.01,
  peakLevel: 0,
  playerEl: null,
  speaking: false,
  speakingStartedAt: 0,
  interruptPlayback: null,
  generation: 0, // bumped on close, so in-flight async work becomes a no-op

  setStatus(text) {
    voiceStatus.textContent = text || '';
  },

  setOrbState(state) {
    voiceOrb.classList.remove('thinking', 'speaking', 'error');
    if (state) voiceOrb.classList.add(state);
    voiceOrb.style.transform = '';
  },

  async open() {
    if (this.active) return;
    this.active = true;
    this.generation += 1;
    voiceOverlay.hidden = false;
    voiceTranscript.textContent = '';
    this.setOrbState(null);
    this.setStatus('মাইক্রোফোন প্রস্তুত করা হচ্ছে…');

    /*
     * "Unlock" audio playback while still inside the click handler's user
     * gesture: browsers grant autoplay permission to a media element only
     * around a gesture, but by the time a TTS reply is ready several
     * network round-trips later, that window has long closed. A media
     * element that has already started playing once (even silence, here)
     * keeps its autoplay eligibility for later .play() calls on the same
     * element, so this is created and started synchronously, before the
     * getUserMedia await below spends the gesture.
     */
    if (!this.playerEl) this.playerEl = new Audio();
    const SILENT_WAV =
      'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=';
    this.playerEl.src = SILENT_WAV;
    this.playerEl.play().catch(() => {});

    if (!navigator.mediaDevices || !window.MediaRecorder) {
      this.setOrbState('error');
      this.setStatus('এই ব্রাউজারে ভয়েস মোড সমর্থিত নয়।');
      return;
    }

    try {
      // Echo cancellation matters here specifically because the mic stays
      // live while the bot's own reply plays out of the speaker (see
      // listen()'s barge-in handling below) -- without it, the bot's own
      // voice leaking back into the mic would trip the barge-in detector.
      //
      // The other two WebRTC processors are deliberately OFF. Both are tuned
      // for a human listener on a call, and both hurt here:
      //   - autoGainControl ramps over a few hundred ms, so a one-word turn
      //     ("hi", "হ্যালো") ends before the gain has come up -- the whole
      //     word arrives attenuated, under the speech gate below.
      //   - noiseSuppression pumps and smears the spectrum. A person hears
      //     that as cleaner; an acoustic model sees artefacts absent from its
      //     training data, and word error goes up.
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: false, autoGainControl: false },
      });
    } catch (err) {
      this.setOrbState('error');
      this.setStatus('মাইক্রোফোন ব্যবহারের অনুমতি পাওয়া যায়নি।');
      return;
    }

    this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const source = this.audioCtx.createMediaStreamSource(this.stream);
    this.analyser = this.audioCtx.createAnalyser();
    this.analyser.fftSize = 512;
    source.connect(this.analyser);

    this.listen();
  },

  close() {
    if (!this.active) return;
    this.active = false;
    this.generation += 1;

    clearTimeout(this.silenceTimer);
    clearTimeout(this.maxDurationTimer);
    if (this.levelRaf) cancelAnimationFrame(this.levelRaf);

    if (this.recorder && this.recorder.state !== 'inactive') {
      try { this.recorder.stop(); } catch (e) {}
    }
    this.recorder = null;

    if (this.playerEl) {
      this.playerEl.pause();
    }
    this.speaking = false;
    this.interruptPlayback = null;

    if (this.stream) {
      this.stream.getTracks().forEach((t) => t.stop());
      this.stream = null;
    }
    if (this.audioCtx) {
      this.audioCtx.close().catch(() => {});
      this.audioCtx = null;
    }

    voiceDebug.hidden = true;
    voiceOverlay.hidden = true;
  },

  toggleMute() {
    this.muted = !this.muted;
    voiceMuteBtn.classList.toggle('muted', this.muted);
    if (this.muted && this.recorder && this.recorder.state === 'recording') {
      this.recorder.stop();
    } else if (!this.muted && this.active && (!this.recorder || this.recorder.state !== 'recording')) {
      this.listen();
    }
    this.setStatus(this.muted ? 'মাইক্রোফোন বন্ধ আছে' : '');
  },

  // Continuously watches mic input level: waits for speech to start, then
  // auto-stops once the user has gone quiet for a beat.
  listen() {
    if (!this.active || this.muted) return;
    const myGen = this.generation;

    this.chunks = [];
    this.speechStarted = false;
    this.peakLevel = 0;
    if (VOICE_DEBUG) voiceDebug.hidden = false;
    let recorder;
    try {
      recorder = new MediaRecorder(this.stream);
    } catch (err) {
      this.setOrbState('error');
      this.setStatus('রেকর্ডিং শুরু করা যায়নি।');
      return;
    }
    this.recorder = recorder;
    const mimeType = recorder.mimeType;

    recorder.addEventListener('dataavailable', (e) => {
      if (e.data && e.data.size > 0) this.chunks.push(e.data);
    });

    recorder.addEventListener('stop', () => {
      if (myGen !== this.generation) return;
      clearTimeout(this.silenceTimer);
      clearTimeout(this.maxDurationTimer);
      if (this.levelRaf) cancelAnimationFrame(this.levelRaf);
      const blob = new Blob(this.chunks, { type: mimeType });
      if (blob.size > 300 && this.speechStarted) {
        this.handleUtterance(blob, myGen);
      } else if (this.active && !this.muted) {
        this.listen(); // false start (silence-only clip) -- keep listening
      }
    });

    recorder.start();
    this.setOrbState(null);
    this.setStatus('শুনছি…');

    // Every bar below is a MULTIPLE of the measured room noise floor (see
    // this.noiseFloor), not an absolute level. Fixed numbers can't work
    // across setups: a headset in a quiet room and a laptop mic in an
    // office differ by an order of magnitude, and one constant tuned for
    // either deafens or false-triggers on the other. The max() floors are
    // only a sanity bound for a pathologically silent input.
    //
    // Onset is two-tiered, which is what makes short words survive.
    // Requiring one bar held for a single duration forces a trade: long
    // enough to reject a click is longer than "hi" or "হ্যালো" spends above
    // it, since a short word is a fast attack straight into a decay with no
    // plateau. So a moderate level must hold for CONFIRM_MS, OR a clearly
    // loud one for just BURST_MS -- transients are rejected by needing
    // duration at moderate level, short words get in on amplitude instead.
    //
    // Starting a turn and holding one open need different bars. Speech dips
    // low constantly -- between syllables, on unvoiced consonants, at the
    // quiet tail of a phrase -- so once speech is under way SUSTAIN holds
    // the turn open frame by frame, and only real silence ends it.
    // The MIN floors are only a guard against a pathologically silent input
    // (a muted or dead mic reading near zero, where any ratio to the noise
    // floor is meaningless). They are deliberately far BELOW real speech:
    // with autoGainControl off, a laptop mic at arm's length reads well
    // under the levels an AGC-inflated signal used to show, so a MIN set
    // from those old numbers sits above actual speech and the gate never
    // opens at all. The noise-floor ratios do the real discrimination.
    const SPEECH_X = 4, SPEECH_MIN = 0.008;
    const BURST_X = 9, BURST_MIN = 0.02;
    // Sustain is the trap. It must clear the noise floor by enough that room
    // noise cannot hold a turn open on its own -- a bar just above the floor
    // means every frame "sustains", the silence timer never fires, and a
    // one-word turn runs to MAX_UTTERANCE_MS and reaches the ASR as one word
    // plus 45s of silence (which transcribes to nothing). So it is also
    // scaled to how loud THIS speaker actually is: PEAK_X of the loudest
    // frame seen this turn. A quiet talker gets a proportionally quiet
    // hangover bar, a loud one a higher bar, and neither is set by guessing
    // an absolute level.
    const SUSTAIN_X = 3, SUSTAIN_MIN = 0.008, SUSTAIN_PEAK_X = 0.18;
    const BARGE_IN_X = 10, BARGE_IN_MIN = 0.025;
    const CONFIRM_MS = 60;
    const BURST_MS = 30;
    const BARGE_IN_GRACE_MS = 400;
    const SILENCE_MS = 1000;
    // Belt and braces, independent of every threshold above: however well
    // SUSTAIN is tuned, sustain-only frames must not be able to extend a
    // turn indefinitely. If nothing has cleared the (much higher) speech bar
    // for this long, the turn ends no matter what sustain thinks -- so a
    // mistuned bar costs a slightly late cutoff, never a 45-second clip.
    const MAX_HANGOVER_MS = 2500;
    const MAX_UTTERANCE_MS = 45000;
    const data = new Uint8Array(this.analyser.fftSize);
    let loudStreakStart = null;
    let burstStreakStart = null;
    let lastLoudAt = null;

    this.maxDurationTimer = setTimeout(() => {
      if (this.recorder && this.recorder.state === 'recording') this.recorder.stop();
    }, MAX_UTTERANCE_MS);

    const tick = () => {
      if (myGen !== this.generation || !this.recorder || this.recorder.state !== 'recording') return;
      this.analyser.getByteTimeDomainData(data);
      let sumSquares = 0;
      for (let i = 0; i < data.length; i++) {
        const v = (data[i] - 128) / 128;
        sumSquares += v * v;
      }
      const level = Math.sqrt(sumSquares / data.length);
      if (level > this.peakLevel) this.peakLevel = level;
      voiceOrb.style.transform = 'scale(' + (1 + Math.min(level * 3, 0.35)) + ')';

      // Track the room's quiet level, asymmetrically: it falls fast (~1s) and
      // rises very slowly (~20s), so speech barely nudges it upward while a
      // fan switching on is still picked up eventually. Frozen once a turn is
      // under way, and while the assistant is talking -- its own voice
      // leaking past the echo canceller must not be learned as "the room".
      if (!this.speechStarted && !this.speaking) {
        const rate = level > this.noiseFloor ? 0.0008 : 0.02;
        this.noiseFloor += (level - this.noiseFloor) * rate;
        this.noiseFloor = Math.min(Math.max(this.noiseFloor, 0.0015), 0.05);
      }
      const floor = this.noiseFloor;
      const speechBar = Math.max(SPEECH_MIN, floor * SPEECH_X);
      const burstBar = Math.max(BURST_MIN, floor * BURST_X);
      const sustainBar = Math.max(
        SUSTAIN_MIN, floor * SUSTAIN_X, this.peakLevel * SUSTAIN_PEAK_X
      );
      const bargeInBar = Math.max(BARGE_IN_MIN, floor * BARGE_IN_X);

      const now = performance.now();
      // Mid-playback, only a real barge-in counts, and only one bar applies --
      // a short-word escape hatch there would hand the turn to the
      // assistant's own leaked voice.
      if (this.speaking) {
        const over =
          level > bargeInBar && now - this.speakingStartedAt > BARGE_IN_GRACE_MS;
        loudStreakStart = over ? (loudStreakStart ?? now) : null;
        burstStreakStart = null;
      } else {
        loudStreakStart = level > speechBar ? (loudStreakStart ?? now) : null;
        burstStreakStart = level > burstBar ? (burstStreakStart ?? now) : null;
      }
      const loud =
        (loudStreakStart !== null && now - loudStreakStart >= CONFIRM_MS) ||
        (burstStreakStart !== null && now - burstStreakStart >= BURST_MS);
      // Mid-utterance, a softer level is enough to hold the turn open. Not
      // while this.speaking: during playback only a real barge-in counts, or
      // the assistant's own voice would keep the mic open forever.
      const sustaining =
        this.speechStarted && !this.speaking && level > sustainBar;

      if (loud) {
        if (this.speaking && this.interruptPlayback) {
          this.interruptPlayback();
          this.interruptPlayback = null;
          this.setOrbState(null);
          this.setStatus('শুনছি…');
        }
        this.speechStarted = true;
        lastLoudAt = now;
      }

      if (
        this.speechStarted &&
        lastLoudAt !== null &&
        now - lastLoudAt > MAX_HANGOVER_MS
      ) {
        this.recorder.stop();
        return;
      }

      if (loud || sustaining) {
        clearTimeout(this.silenceTimer);
        this.silenceTimer = setTimeout(() => {
          if (this.recorder && this.recorder.state === 'recording') this.recorder.stop();
        }, SILENCE_MS);
      }

      if (VOICE_DEBUG) {
        const f = (n) => n.toFixed(4);
        voiceDebug.textContent =
          'rms ' + f(level) + '   peak ' + f(this.peakLevel) +
          '   floor ' + f(floor) + '\n' +
          'speech>' + f(speechBar) + '  burst>' + f(burstBar) +
          '  sustain>' + f(sustainBar) + '\n' +
          (this.speechStarted ? 'SPEECH' : 'waiting') +
          (lastLoudAt !== null
            ? ' +' + ((now - lastLoudAt) / 1000).toFixed(1) + 's'
            : '') +
          (loud ? ' loud' : '') + (sustaining ? ' sustain' : '') +
          (this.speaking ? ' | playing (barge>' + f(bargeInBar) + ')' : '');
      }

      this.levelRaf = requestAnimationFrame(tick);
    };
    this.levelRaf = requestAnimationFrame(tick);
  },

  async handleUtterance(blob, myGen) {
    this.setOrbState('thinking');
    this.setStatus('শুনছি থেকে লিখছে…');
    let text = '';
    try {
      // Trim the VAD's trailing hangover before upload -- see prepareForAsr.
      // A failure here is not fatal: fall back to the raw recording, which
      // still transcribes for anything longer than a word or two.
      let clip = blob;
      try {
        const trimmed = await prepareForAsr(blob);
        if (!trimmed) {
          // Speech was detected live but the clip holds none -- a transient
          // that cleared the gate. Keep listening rather than asking the
          // ASR to transcribe silence.
          if (myGen === this.generation && this.active) this.listen();
          return;
        }
        clip = trimmed;
      } catch (prepErr) {
        clip = blob;
      }
      text = await transcribe(clip);
    } catch (err) {
      if (myGen !== this.generation) return;
      this.setOrbState('error');
      this.setStatus('রূপান্তর ব্যর্থ হয়েছে, আবার চেষ্টা করুন।');
      setTimeout(() => { if (this.active) this.listen(); }, 1500);
      return;
    }
    if (myGen !== this.generation) return;

    if (!text) {
      this.setStatus('কিছু শোনা যায়নি, আবার বলুন।');
      this.listen();
      return;
    }

    voiceTranscript.textContent = text;
    addUserMessage(text);
    this.setOrbState('thinking');
    this.setStatus('ভাবছে…');

    let result;
    try {
      result = await ask(text, 'voice');
    } catch (err) {
      result = { text: '', failed: true };
    }
    if (myGen !== this.generation) return;

    if (!result || result.failed || !result.text) {
      this.setOrbState('error');
      this.setStatus('উত্তর তৈরি করা যায়নি, আবার চেষ্টা করুন।');
      setTimeout(() => { if (this.active) this.listen(); }, 1500);
      return;
    }

    voiceTranscript.textContent = result.text.length > 220
      ? result.text.slice(0, 220) + '…'
      : result.text;
    this.setOrbState('thinking');
    this.setStatus('কণ্ঠস্বর তৈরি করা হচ্ছে…');

    // Marks the moment the first audio actually sounds -- not when the
    // request was sent. Barge-in's grace period is measured from here, so
    // it must not start ticking during synthesis, when there is nothing
    // playing to barge in on.
    const beginSpeaking = () => {
      if (myGen !== this.generation) return;
      this.setOrbState('speaking');
      this.setStatus('বলছে… (থামাতে কথা বলুন)');
      this.speaking = true;
      this.speakingStartedAt = performance.now();
    };
    const doneSpeaking = () => {
      this.speaking = false;
      this.interruptPlayback = null;
      if (myGen !== this.generation) return;
      this.setOrbState(null);
      this.setStatus('শুনছি…');
      // Safety net: listen() should already be running (started below,
      // concurrently with playback), but restart it if it somehow died.
      if (!this.recorder || this.recorder.state !== 'recording') this.listen();
    };

    /*
     * Start listening immediately, concurrently with playback, instead of
     * waiting for the reply to finish -- this is what makes barge-in
     * possible at all. Without it the mic is simply off while the bot
     * talks and there is nothing to interrupt with.
     */
    this.listen();

    // The mic's own context is reused for playback so both share one clock;
    // it is also already unlocked by the opening gesture, which a context
    // created here would not be.
    try {
      let interrupted = false;
      await speakStreaming(
        result.text,
        this.audioCtx,
        beginSpeaking,
        (stop) => {
          // Exposed so listen()'s tick loop can cut the reply off the
          // instant it detects the user talking over it.
          this.interruptPlayback = () => {
            interrupted = true;
            stop();
            this.speaking = false;
            this.interruptPlayback = null;
          };
        }
      );
      if (myGen !== this.generation) return;
      // After a barge-in the user is already mid-sentence and listen() is
      // recording it; announcing "finished speaking" here would reset the
      // orb and status out from under them.
      if (!interrupted) doneSpeaking();
      return;
    } catch (err) {
      if (myGen !== this.generation) return;
      // Fall through to the buffered path below: streaming is the fast
      // route, not the only one, and a reply the user can hear late beats
      // one they cannot hear at all.
      this.speaking = false;
      this.interruptPlayback = null;
    }

    let audioUrl;
    try {
      audioUrl = await synthesizeSpeech(result.text);
    } catch (err) {
      if (myGen !== this.generation) return;
      // TTS failed (e.g. the voice server is out of GPU memory) -- still
      // move on and keep the conversation going by text.
      this.setOrbState('error');
      this.setStatus('কণ্ঠস্বর তৈরি ব্যর্থ হয়েছে, লেখায় উত্তর দেখুন।');
      setTimeout(() => { if (this.active) this.listen(); }, 1500);
      return;
    }
    if (myGen !== this.generation) return;

    const audio = this.playerEl;
    audio.src = audioUrl;
    beginSpeaking();

    const cleanupAudio = () => {
      audio.removeEventListener('ended', onEnded);
      audio.removeEventListener('error', onError);
      URL.revokeObjectURL(audioUrl);
      this.speaking = false;
      this.interruptPlayback = null;
    };
    const onEnded = () => {
      cleanupAudio();
      doneSpeaking();
    };
    const onError = () => {
      cleanupAudio();
      if (myGen !== this.generation) return;
      this.setOrbState('error');
      this.setStatus('অডিও চালানো সম্ভব হয়নি।');
      if (!this.recorder || this.recorder.state !== 'recording') this.listen();
    };
    audio.addEventListener('ended', onEnded);
    audio.addEventListener('error', onError);
    this.interruptPlayback = () => {
      audio.pause();
      cleanupAudio();
    };

    try {
      await audio.play();
    } catch (err) {
      onError();
    }
  },
};

micBtn.addEventListener('click', () => VoiceMode.open());
voiceCloseBtn.addEventListener('click', () => VoiceMode.close());
voiceMuteBtn.addEventListener('click', () => VoiceMode.toggleMute());
