#!/usr/bin/env python3
"""
Smoke test OpenAI Realtime (Programme seul)
===========================================
Teste connexion WS, envoi audio et reception d'evenements.

Usage:
    python scripts/mock/realtime_smoke.py --audio data/corpus_audio/speech_clean_48k.wav
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import wave
from pathlib import Path

# Ajouter src au path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def _load_wav_mono_24k(path: Path) -> bytes:
    with wave.open(str(path), "rb") as wf:
        channels = wf.getnchannels()
        rate = wf.getframerate()
        width = wf.getsampwidth()
        data = wf.readframes(wf.getnframes())

    if width != 2:
        raise RuntimeError("WAV doit etre en PCM16")

    if rate != 24000 or channels != 1:
        raise RuntimeError("WAV doit etre 24kHz mono (PCM16)")

    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test OpenAI Realtime")
    parser.add_argument("--audio", type=str, help="WAV PCM16 24k mono a envoyer")
    parser.add_argument("--duration", type=float, default=4.0, help="Duree d'attente (s)")
    args = parser.parse_args()

    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        print("[SKIP] OPENAI_API_KEY non defini")
        return 2

    try:
        from assistant.realtime.client import create_parapharmacie_client
        from assistant.audio.half_duplex import HalfDuplexManager, HalfDuplexConfig
    except Exception as e:
        print(f"[ERREUR] Import realtime: {e}")
        return 1

    client = create_parapharmacie_client(api_key=api_key)

    events = {"connected": False, "audio": 0, "transcript": 0, "errors": 0}

    def on_connected():
        events["connected"] = True
        print("[EVENT] Connected")

    def on_audio_received(audio):
        events["audio"] += 1
        print(f"[EVENT] Audio received: {len(audio)} bytes")

    def on_transcript(text):
        events["transcript"] += 1
        print(f"[EVENT] Transcript: {text}")

    def on_error(error):
        events["errors"] += 1
        print(f"[EVENT] Error: {error}")

    client.on("on_connected", on_connected)
    client.on("on_audio_received", on_audio_received)
    client.on("on_transcript", on_transcript)
    client.on("on_error", on_error)

    print("[TEST] Connexion...")
    if not client.connect():
        print("[FAIL] Connexion echouee")
        return 1

    # Envoi audio
    if args.audio:
        audio_path = Path(args.audio)
        if not audio_path.exists():
            print(f"[ERREUR] Fichier introuvable: {audio_path}")
            return 1
        try:
            audio_bytes = _load_wav_mono_24k(audio_path)
        except Exception as e:
            print(f"[ERREUR] Audio invalide: {e}")
            return 1
    else:
        # 1s de silence 24k mono
        audio_bytes = bytes(24000 * 2)

    print("[TEST] Envoi audio...")
    client.send_audio(audio_bytes)

    # Test half-duplex local (logique)
    print("[TEST] Half-duplex local...")
    hd = HalfDuplexManager(HalfDuplexConfig(cooldown_ms=200, log_state_changes=True))
    hd.start_speaking()
    test_audio = bytes([0x01, 0x02] * 1000)
    filtered = hd.filter_input_audio(test_audio)
    if filtered != bytes(len(test_audio)):
        print("[FAIL] Half-duplex: audio non coupe pendant parole")
        client.disconnect()
        return 1
    hd.stop_speaking()
    time.sleep(0.25)
    filtered = hd.filter_input_audio(test_audio)
    if filtered != test_audio:
        print("[FAIL] Half-duplex: audio non retabli apres cooldown")
        client.disconnect()
        return 1
    hd.cleanup()

    time.sleep(args.duration)
    client.disconnect()

    if events["errors"] > 0 or not events["connected"]:
        print("[FAIL] Realtime: erreurs detectees")
        return 1

    print("[OK] Realtime smoke test termine")
    return 0


if __name__ == "__main__":
    sys.exit(main())
