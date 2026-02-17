#!/usr/bin/env python3
# Fallback vocal HTTP: micro Pepper -> transcription HTTP -> réponse HTTP -> TTS Pepper

from __future__ import annotations

import io
import queue
import threading
import time
import wave
from collections import deque
from dataclasses import dataclass
from typing import Callable, Optional, Dict, Any

import numpy as np
from openai import OpenAI


@dataclass
class VoiceFallbackConfig:
    input_sample_rate: int = 48000
    input_channels: int = 4
    target_sample_rate: int = 16000
    speech_threshold: float = 0.015
    end_silence_s: float = 0.75
    min_utterance_s: float = 0.55
    max_utterance_s: float = 12.0
    pre_roll_s: float = 0.25
    queue_max_chunks: int = 256
    transcription_model: str = "whisper-1"
    language: str = "fr"
    manual_trigger: bool = False
    listen_window_s: float = 8.0


class HTTPVoiceFallback:
    # Pipeline vocal de secours côté HTTP.

    def __init__(
        self,
        api_key: str,
        text_client,
        speak_callback: Callable[[str], None],
        context_provider: Optional[Callable[[], Dict[str, Any]]] = None,
        on_transcript: Optional[Callable[[str], None]] = None,
        on_answer: Optional[Callable[[str, str], None]] = None,
        config: Optional[VoiceFallbackConfig] = None,
    ):
        self.config = config or VoiceFallbackConfig()
        self._openai = OpenAI(api_key=api_key)
        self._text_client = text_client
        self._speak_callback = speak_callback
        self._context_provider = context_provider or (lambda: {})
        self._on_transcript = on_transcript
        self._on_answer = on_answer

        self._queue: "queue.Queue[bytes]" = queue.Queue(maxsize=self.config.queue_max_chunks)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._pre_roll = deque()
        self._pre_roll_max_samples = int(self.config.pre_roll_s * self.config.input_sample_rate)
        self._in_speech = False
        self._speech_samples = []
        self._speech_len_s = 0.0
        self._silence_s = 0.0
        self._noise_floor = 0.005
        self._mute_until = 0.0
        self._listen_until = 0.0 if self.config.manual_trigger else float("inf")

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._drain_queue()
        self._reset_vad_state()

    def ingest(self, audio_bytes: bytes):
        if not audio_bytes or self._stop_event.is_set():
            return
        try:
            self._queue.put_nowait(audio_bytes)
        except queue.Full:
            # On jette les chunks les plus anciens pour garder le temps réel.
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(audio_bytes)
            except Exception:
                pass

    def arm_listen_window(self, duration_s: Optional[float] = None):
        # Active une fenêtre d'écoute temporaire (mode manuel).
        if not self.config.manual_trigger:
            return
        window = float(duration_s or self.config.listen_window_s)
        self._listen_until = time.time() + max(0.5, window)
        self._reset_vad_state()
        self._drain_queue(max_items=128)

    def is_listen_window_open(self) -> bool:
        if not self.config.manual_trigger:
            return True
        return time.time() <= self._listen_until

    def _run_loop(self):
        while not self._stop_event.is_set():
            try:
                chunk = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if self.config.manual_trigger and time.time() > self._listen_until:
                continue

            if time.time() < self._mute_until:
                continue

            mono_i16 = self._to_mono_i16(chunk)
            if mono_i16.size == 0:
                continue

            chunk_duration_s = mono_i16.size / float(self.config.input_sample_rate)
            rms = self._rms_norm(mono_i16)

            if not self._in_speech:
                self._update_noise_floor(rms)
                self._push_pre_roll(mono_i16)
                if rms > self._speech_start_threshold():
                    self._in_speech = True
                    self._speech_samples = list(self._pre_roll)
                    self._speech_samples.append(mono_i16)
                    self._speech_len_s = sum(a.size for a in self._speech_samples) / float(self.config.input_sample_rate)
                    self._silence_s = 0.0
                continue

            # En cours de parole
            self._speech_samples.append(mono_i16)
            self._speech_len_s += chunk_duration_s

            if rms < self._speech_end_threshold():
                self._silence_s += chunk_duration_s
            else:
                self._silence_s = 0.0

            if self._speech_len_s >= self.config.max_utterance_s:
                self._finalize_utterance()
                continue

            if self._silence_s >= self.config.end_silence_s:
                self._finalize_utterance()

    def _reset_vad_state(self):
        self._in_speech = False
        self._speech_samples = []
        self._speech_len_s = 0.0
        self._silence_s = 0.0

    def _finalize_utterance(self):
        utterance_s = self._speech_len_s
        samples = self._concat_samples(self._speech_samples)
        self._reset_vad_state()
        self._pre_roll.clear()

        if utterance_s < self.config.min_utterance_s:
            return
        if samples.size == 0:
            return

        try:
            wav_bytes = self._pcm_to_wav(
                self._resample_i16(samples, self.config.input_sample_rate, self.config.target_sample_rate),
                sample_rate=self.config.target_sample_rate
            )
            transcript = self._transcribe_wav(wav_bytes).strip()
            if not transcript:
                return
            if self._on_transcript:
                self._on_transcript(transcript)

            context = self._context_provider() if self._context_provider else {}
            answer = (self._text_client.ask(transcript, context) or "").strip()
            if not answer:
                return
            if self._on_answer:
                self._on_answer(transcript, answer)

            # Éviter l'auto-capture pendant/par juste après TTS.
            self._mute_until = time.time() + 0.5
            self._speak_callback(answer)
            self._mute_until = time.time() + 0.8
            self._drain_queue(max_items=256)
        except Exception:
            # Le fallback ne doit jamais casser le runtime principal.
            return

    def _transcribe_wav(self, wav_bytes: bytes) -> str:
        bio = io.BytesIO(wav_bytes)
        bio.name = "pepper_fallback.wav"
        out = self._openai.audio.transcriptions.create(
            model=self.config.transcription_model,
            file=bio,
            language=self.config.language
        )
        return getattr(out, "text", "") or ""

    def _drain_queue(self, max_items: int = 1024):
        for _ in range(max_items):
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def _push_pre_roll(self, samples_i16: np.ndarray):
        self._pre_roll.append(samples_i16)
        total = sum(a.size for a in self._pre_roll)
        while total > self._pre_roll_max_samples and self._pre_roll:
            removed = self._pre_roll.popleft()
            total -= removed.size

    def _update_noise_floor(self, rms: float):
        self._noise_floor = 0.98 * self._noise_floor + 0.02 * rms

    def _speech_start_threshold(self) -> float:
        return max(self.config.speech_threshold, self._noise_floor * 3.0)

    def _speech_end_threshold(self) -> float:
        return max(self.config.speech_threshold * 0.7, self._noise_floor * 2.0)

    @staticmethod
    def _concat_samples(chunks) -> np.ndarray:
        if not chunks:
            return np.array([], dtype=np.int16)
        return np.concatenate(chunks).astype(np.int16, copy=False)

    def _to_mono_i16(self, pcm_bytes: bytes) -> np.ndarray:
        if not pcm_bytes:
            return np.array([], dtype=np.int16)
        arr = np.frombuffer(pcm_bytes, dtype=np.int16)
        ch = max(1, int(self.config.input_channels))
        if ch == 1:
            return arr
        frames = len(arr) // ch
        if frames <= 0:
            return np.array([], dtype=np.int16)
        arr = arr[: frames * ch].reshape(frames, ch).astype(np.float32)
        mono = np.mean(arr, axis=1)
        return np.clip(mono, -32768, 32767).astype(np.int16)

    @staticmethod
    def _rms_norm(samples_i16: np.ndarray) -> float:
        if samples_i16.size == 0:
            return 0.0
        x = samples_i16.astype(np.float32) / 32768.0
        return float(np.sqrt(np.mean(x * x) + 1e-12))

    @staticmethod
    def _resample_i16(samples_i16: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
        if src_sr == dst_sr or samples_i16.size == 0:
            return samples_i16.astype(np.int16, copy=False)
        src_len = samples_i16.size
        dst_len = max(1, int(src_len * float(dst_sr) / float(src_sr)))
        x_old = np.linspace(0.0, 1.0, num=src_len, endpoint=False)
        x_new = np.linspace(0.0, 1.0, num=dst_len, endpoint=False)
        y = np.interp(x_new, x_old, samples_i16.astype(np.float32))
        return np.clip(y, -32768, 32767).astype(np.int16)

    @staticmethod
    def _pcm_to_wav(samples_i16: np.ndarray, sample_rate: int) -> bytes:
        bio = io.BytesIO()
        with wave.open(bio, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(samples_i16.tobytes())
        return bio.getvalue()
