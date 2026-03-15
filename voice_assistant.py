#!/usr/bin/env python3
"""Standalone voice assistant with Alexa-style wake word and conversation sessions.

Flow:
  1. Listens for wake word ("Alexa")
  2. Plays a chime / prompt to indicate it's listening
  3. Records speech and transcribes it
  4. Sends to nanobot and speaks the response
  5. Stays in conversation mode — keeps listening for follow-up speech
  6. After SILENCE_TIMEOUT with no speech, returns to wake word mode

Dependencies:
    pip install openwakeword sounddevice numpy edge-tts faster-whisper mpv

Usage:
    python voice_assistant.py
"""

import asyncio
import queue
import subprocess
import sys
import tempfile
import time

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel
from openwakeword.model import Model as WakeModel

# --- Configuration ---
WAKE_WORD_MODEL = "alexa"
WAKE_THRESHOLD = 0.7  # Higher threshold to reduce false positives
SAMPLE_RATE = 16000
CHUNK_SAMPLES = 1280  # 80ms at 16kHz

# Recording settings
LISTEN_SECONDS = 5  # Max recording time per utterance
SILENCE_THRESHOLD = 500  # RMS below this = silence (int16 scale)
SILENCE_CHUNKS = 15  # ~1.2s of silence to stop recording
PRE_BUFFER_SECONDS = 1  # Buffer before wake word

# Session settings
SESSION_TIMEOUT = 8  # Seconds of silence before returning to wake word mode

PRE_BUFFER_CHUNKS = int(PRE_BUFFER_SECONDS * SAMPLE_RATE / CHUNK_SAMPLES)
LISTEN_CHUNKS = int(LISTEN_SECONDS * SAMPLE_RATE / CHUNK_SAMPLES)

WAKE_PHRASES = {"alexa", "hey alexa", "hey nanobot", "nanobot", "ok", "okay"}

# Flag to suppress wake word detection while speaking
_is_speaking = False


def speak(text: str) -> None:
    """Speak text using edge-tts + mpv."""
    global _is_speaking
    import edge_tts

    async def _speak():
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            tmp = f.name
        communicate = edge_tts.Communicate(text, "en-GB-SoniaNeural")
        await communicate.save(tmp)
        subprocess.run(["mpv", "--no-terminal", tmp], check=True)

    _is_speaking = True
    try:
        asyncio.run(_speak())
    finally:
        _is_speaking = False


def strip_wake_word(text: str) -> str:
    """Remove the wake phrase from the transcription."""
    lower = text.strip().lower()
    for phrase in sorted(WAKE_PHRASES, key=len, reverse=True):
        if lower.startswith(phrase):
            lower = lower[len(phrase):].lstrip(" ,.")
            break
    return lower.strip()


def transcribe(whisper: WhisperModel, audio: np.ndarray) -> str:
    """Transcribe audio using faster-whisper with VAD filtering."""
    audio_f32 = audio.astype(np.float32) / 32768.0
    segments, _ = whisper.transcribe(
        audio_f32, beam_size=3, language="en",
        vad_filter=True,
    )
    return " ".join(seg.text.strip() for seg in segments).strip()


def is_silence(chunk: np.ndarray) -> bool:
    """Check if an audio chunk is silence."""
    rms = np.sqrt(np.mean(chunk.astype(np.float32) ** 2))
    return rms < SILENCE_THRESHOLD


def record_utterance(audio_queue: queue.Queue) -> np.ndarray:
    """Record until silence is detected or max time reached."""
    chunks = []
    silent_count = 0

    for _ in range(LISTEN_CHUNKS):
        try:
            chunk = audio_queue.get(timeout=2)
        except queue.Empty:
            break

        chunks.append(chunk)

        if is_silence(chunk):
            silent_count += 1
            if silent_count >= SILENCE_CHUNKS:
                break
        else:
            silent_count = 0

    return np.concatenate(chunks) if chunks else np.array([], dtype=np.int16)


def wait_for_speech(audio_queue: queue.Queue, timeout: float) -> bool:
    """Wait up to timeout seconds for non-silent audio. Returns True if speech detected."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            chunk = audio_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        if not is_silence(chunk):
            return True
    return False


def drain_queue(audio_queue: queue.Queue) -> None:
    """Drain all pending audio from the queue."""
    while not audio_queue.empty():
        try:
            audio_queue.get_nowait()
        except queue.Empty:
            break


def main() -> None:
    print("Loading wake word model...")
    wake_model = WakeModel()

    print("Loading Whisper model (distil-small.en)...")
    whisper = WhisperModel("distil-small.en", device="cpu", compute_type="int8")

    print(f"Ready. Say 'Alexa' to activate (threshold={WAKE_THRESHOLD}).")
    print("Press Ctrl+C to quit.\n")

    audio_queue: queue.Queue[np.ndarray] = queue.Queue()
    pre_buffer: list[np.ndarray] = []

    def audio_callback(indata, frames, time_info, status):
        if status:
            print(f"Audio status: {status}", file=sys.stderr)
        audio_queue.put(indata[:, 0].copy())

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16",
        blocksize=CHUNK_SAMPLES,
        device="pulse",
        callback=audio_callback,
    ):
        try:
            while True:
                # === WAKE WORD MODE ===
                in_session = False

                while not in_session:
                    chunk = audio_queue.get()

                    # Skip wake word detection while TTS is playing
                    if _is_speaking:
                        continue

                    pre_buffer.append(chunk)
                    if len(pre_buffer) > PRE_BUFFER_CHUNKS:
                        pre_buffer.pop(0)

                    prediction = wake_model.predict(chunk)
                    score = prediction.get(WAKE_WORD_MODEL, 0)

                    if score > WAKE_THRESHOLD:
                        print(f"\nWake word detected! ({score:.2f})")
                        in_session = True

                # === CONVERSATION SESSION ===
                # Check if speech came with the wake word (pre-buffer)
                pre_audio = np.concatenate(pre_buffer) if pre_buffer else np.array([], dtype=np.int16)
                pre_buffer.clear()
                wake_model.reset()

                # Record what follows the wake word
                print("  Listening...")
                follow_audio = record_utterance(audio_queue)
                full_audio = np.concatenate([pre_audio, follow_audio])

                text = transcribe(whisper, full_audio)
                utterance = strip_wake_word(text)

                if not utterance:
                    # No speech with wake word — prompt and listen again
                    print("  < \"What can I help you with?\"")
                    speak("What can I help you with?")
                    drain_queue(audio_queue)

                    print("  Listening...")
                    follow_audio = record_utterance(audio_queue)
                    if len(follow_audio) == 0:
                        print("  No speech detected, returning to wake word mode.\n")
                        continue
                    text = transcribe(whisper, follow_audio)
                    utterance = text.strip()

                if not utterance:
                    print("  No speech detected, returning to wake word mode.\n")
                    continue

                # Conversation loop
                while True:
                    print(f"  > \"{utterance}\"")

                    # TODO: Send to nanobot and get real response
                    response = f"You said: {utterance}"

                    print(f"  < \"{response}\"")
                    speak(response)
                    drain_queue(audio_queue)

                    # Wait for follow-up speech or timeout
                    print(f"  Waiting for follow-up ({SESSION_TIMEOUT}s)...")
                    if not wait_for_speech(audio_queue, SESSION_TIMEOUT):
                        print("  Session timed out, returning to wake word mode.\n")
                        drain_queue(audio_queue)
                        wake_model.reset()
                        break

                    # Got speech — record and transcribe
                    print("  Listening...")
                    follow_audio = record_utterance(audio_queue)
                    text = transcribe(whisper, follow_audio)
                    utterance = text.strip()

                    if not utterance:
                        print("  Couldn't understand, returning to wake word mode.\n")
                        drain_queue(audio_queue)
                        wake_model.reset()
                        break

        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
