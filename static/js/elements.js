/*
 * Every element the UI holds on to, looked up once.
 *
 * Module scripts are deferred, so the document is parsed by the time any of
 * this runs -- and gathering the handles in one place keeps the id strings,
 * which have to match index.html exactly, from being scattered over the
 * modules that use them.
 */

export const messagesEl = document.getElementById('messages');
export const formEl = document.getElementById('chat-form');
export const inputEl = document.getElementById('question-input');
export const sendBtn = document.getElementById('send-btn');
export const resetBtn = document.getElementById('reset-btn');
export const micBtn = document.getElementById('mic-btn');
export const jumpBtn = document.getElementById('jump-btn');

export const voiceOverlay = document.getElementById('voice-overlay');
export const voiceOrb = document.getElementById('voice-orb');
export const voiceStatus = document.getElementById('voice-status');
export const voiceDebug = document.getElementById('voice-debug');
export const voiceTranscript = document.getElementById('voice-transcript');
export const voiceMuteBtn = document.getElementById('voice-mute-btn');
export const voiceCloseBtn = document.getElementById('voice-close-btn');
