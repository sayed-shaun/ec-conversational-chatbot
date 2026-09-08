"""The voice path: speech in, speech out, and the text shaping between them.

Kept apart from src/chatbot, which is the conversation itself. The split is
along the seam the code already had: nothing here is imported by the chat
engine, and nothing here imports it. A typed turn touches none of this.

    asr        audio up, transcript back
    tts        text down, audio back
    transform  a reply rewritten into something the Bangla voice can say
"""
