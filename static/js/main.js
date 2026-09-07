/*
 * Entry point: pulls in the modules that wire themselves to the DOM, then
 * opens the conversation.
 *
 * Loaded as type="module", so it runs after the document is parsed and the
 * KaTeX globals in index.html are in place.
 */

import { greet } from './chat.js';
import './viewport.js';
import './voice.js';

greet();
