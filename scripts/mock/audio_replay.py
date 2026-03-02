#!/usr/bin/env python3
# Replay audio (Programme seul)

from __future__ import annotations

import argparse
import math
import sys
import time
import wave
from pathlib import Path
from typing import List

# Ajouter src au path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def _rms(pcm16: bytes) -> float:
    # Gere l'action.
    if not pcm16:
        return 0.0
    total = 0
    count = len(pcm16) // 2
    for i in range(0, len(pcm16), 2):
        sample = int.from_bytes(pcm16[i:i+2], byteorder="little", signed=True)
        total += sample * sample
    return math.sqrt(total / max(1, count))


def main() -> int:
    # Gere l'action.
    parser = argparse.ArgumentParser(description="Replay audio 4ch -> pipeline")
    parser.add_argument("--input", type=str, required=True, help="WAV 4ch 48kHz")
    parser.add_argument("--chunk-frames", type=int, default=1024, help="Frames par chunk")
    parser.add_argument("--no-realtime", action="store_true", help="Ne pas respecter le temps reel")
    parser.add_argument("--output", type=str, help="Sauvegarde WAV de sortie (24k mono)")
    args = parser.parse_args()

    try:
        from assistant.audio.processing import AudioProcessor, AudioConfig
    except Exception as e:
        print(f"[ERREUR] Import audio: {e}")
        return 1

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[ERREUR] Fichier introuvable: {input_path}")
        return 1

    with wave.open(str(input_path), "rb") as wf:
        channels = wf.getnchannels()
        sample_rate = wf.getframerate()
        sampwidth = wf.getsampwidth()
        total_frames = wf.getnframes()

        print(f"[INFO] WAV: {channels}ch, {sample_rate}Hz, {sampwidth*8}-bit, {total_frames} frames")

        if channels != 4 or sample_rate != 48000 or sampwidth != 2:
            print("[WARN] Format inattendu (attendu: 4ch/48k/16-bit)")

        config = AudioConfig(
            input_sample_rate=sample_rate,
            output_sample_rate=24000,
            input_channels=channels,
            output_channels=1,
        )
        processor = AudioProcessor(config)

        output_chunks: List[bytes] = []
        silence_chunks = 0
        total_chunks = 0

        start = time.time()
        while True:
            data = wf.readframes(args.chunk_frames)
            if not data:
                break

            total_chunks += 1
            out = processor.process(data)
            output_chunks.append(out)

            if _rms(out) < 200:
                silence_chunks += 1

            if not args.no_realtime:
                time.sleep(args.chunk_frames / sample_rate)

        elapsed = time.time() - start

    output_bytes = b"".join(output_chunks)
    input_samples = total_frames * channels
    output_samples = len(output_bytes) // 2
    expected_output_samples = int(total_frames * (24000 / sample_rate))
    ratio = output_samples / max(1, expected_output_samples)

    print("\n[STATS]")
    print(f"  Duree replay: {elapsed:.2f}s")
    print(f"  Samples entree: {input_samples}")
    print(f"  Samples sortie: {output_samples} (attendu ~{expected_output_samples})")
    print(f"  Ratio sortie/attendu: {ratio:.3f}")
    print(f"  Chunks silencieux: {silence_chunks}/{total_chunks}")
    print(f"  RMS sortie: {_rms(output_bytes):.1f}")

    # Sauvegarde optionnelle
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out_path), "wb") as wf_out:
            wf_out.setnchannels(1)
            wf_out.setsampwidth(2)
            wf_out.setframerate(24000)
            wf_out.writeframes(output_bytes)
        print(f"[SAVE] WAV sortie: {out_path}")

    # Critere simple: ratio proche + non silencieux
    pass_ratio = 0.95 <= ratio <= 1.05
    pass_audio = _rms(output_bytes) > 100
    if pass_ratio and pass_audio:
        print("\n[OK] Replay audio valide")
        return 0

    print("\n[FAIL] Replay audio invalide")
    return 1


if __name__ == "__main__":
    sys.exit(main())
