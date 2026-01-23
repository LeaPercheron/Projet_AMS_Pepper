#!/usr/bin/env python3
"""
Test Module Audio
=================
Teste le pipeline de traitement audio.

Usage:
    python scripts/test_audio.py
    python scripts/test_audio.py --preset noisy_room
    python scripts/test_audio.py --with-file input.wav
"""

import sys
import argparse
import time
from pathlib import Path

# Ajouter src au path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from assistant.audio import (
    AudioProcessor,
    AudioConfig,
    BeamformingMode,
    get_preset_config,
    HalfDuplexManager,
    HalfDuplexConfig,
    SpeakingState
)


def test_audio_processing():
    """Teste le traitement audio avec signal synthetique."""
    import numpy as np

    print("=" * 60)
    print("TEST TRAITEMENT AUDIO")
    print("=" * 60)

    # Configuration
    config = AudioConfig()
    processor = AudioProcessor(config)

    print(f"\nConfiguration:")
    print(f"  Entree: {config.input_sample_rate}Hz, {config.input_channels}ch")
    print(f"  Sortie: {config.output_sample_rate}Hz, {config.output_channels}ch")
    print(f"  Beamforming: {config.beamforming_enabled}")
    print(f"  Reduction bruit: {config.noise_reduction_enabled}")
    print(f"  AGC: {config.agc_enabled}")

    # Generer signal de test (1 seconde, 4 canaux)
    duration = 1.0
    t = np.linspace(0, duration, int(config.input_sample_rate * duration))

    # Voix simulee (sinusoide modulee) + bruit
    voice = 0.3 * np.sin(2 * np.pi * 300 * t) * (1 + 0.5 * np.sin(2 * np.pi * 5 * t))
    noise = 0.05 * np.random.randn(len(t))

    # Canaux avec volumes differents (front plus fort)
    ch_front = voice + noise
    ch_rear = 0.2 * voice + noise * 1.5
    ch_left = 0.6 * voice + noise * 1.2
    ch_right = 0.6 * voice + noise * 1.2

    audio_4ch = np.column_stack([ch_front, ch_rear, ch_left, ch_right])
    audio_bytes = (audio_4ch.flatten() * 32767).astype(np.int16).tobytes()

    print(f"\nSignal de test:")
    print(f"  Duree: {duration}s")
    print(f"  Samples: {len(t)} x 4 canaux")
    print(f"  Taille: {len(audio_bytes)} bytes")

    # Traiter
    print("\nTraitement...")
    start = time.time()
    output_bytes = processor.process(audio_bytes)
    elapsed = (time.time() - start) * 1000

    stats = processor.get_stats()
    print(f"\nResultats:")
    print(f"  Entree: {stats['input_samples']} samples ({stats['input_level_db']:.1f} dB)")
    print(f"  Sortie: {stats['output_samples']} samples ({stats['output_level_db']:.1f} dB)")
    print(f"  Gain applique: {stats['gain_applied_db']:.1f} dB")
    print(f"  Clipping: {stats['clipping_count']}")
    print(f"  Temps traitement: {elapsed:.2f} ms")

    # Verifier resampling
    expected = int(stats['input_samples'] * config.output_sample_rate / config.input_sample_rate)
    print(f"\n  Resampling: {stats['input_samples']} -> {stats['output_samples']} (attendu: ~{expected})")

    return True


def test_presets():
    """Teste les differents presets audio."""
    print("\n" + "=" * 60)
    print("TEST PRESETS")
    print("=" * 60)

    presets = ['default', 'quiet_room', 'noisy_room', 'far_field', 'close_talk']

    for preset in presets:
        config = get_preset_config(preset)
        processor = AudioProcessor(config)

        print(f"\n[{preset}]")
        print(f"  Noise reduction: {config.noise_reduction_strength}")
        print(f"  AGC max gain: {config.max_gain_db} dB")
        print(f"  Front weight: {config.front_weight}")

    return True


def test_half_duplex():
    """Teste le gestionnaire half-duplex."""
    print("\n" + "=" * 60)
    print("TEST HALF-DUPLEX")
    print("=" * 60)

    config = HalfDuplexConfig(
        cooldown_ms=200,
        log_state_changes=True
    )
    manager = HalfDuplexManager(config)

    # Callback
    def on_state_change(state):
        print(f"  -> Callback: {state.value}")

    manager.register_callback(on_state_change)

    # Test audio
    test_audio = bytes([0x00, 0x10] * 500)

    print("\n[1] Etat initial")
    print(f"  Etat: {manager.state.value}")
    print(f"  is_speaking: {manager.is_speaking}")
    filtered = manager.filter_input_audio(test_audio)
    print(f"  Audio: {'original' if filtered == test_audio else 'silence'}")

    print("\n[2] Debut parole")
    manager.start_speaking()
    filtered = manager.filter_input_audio(test_audio)
    print(f"  Audio: {'original' if filtered == test_audio else 'silence'}")

    print("\n[3] Fin parole")
    manager.stop_speaking()
    print(f"  Etat: {manager.state.value}")

    print("\n[4] Apres cooldown...")
    time.sleep(0.3)
    print(f"  Etat: {manager.state.value}")

    print("\n[5] Statistiques")
    stats = manager.get_stats()
    for k, v in stats.items():
        print(f"  {k}: {v}")

    manager.cleanup()
    return True


def main():
    parser = argparse.ArgumentParser(description="Test module audio")
    parser.add_argument("--preset", type=str, default="default",
                        help="Preset audio a utiliser")
    parser.add_argument("--with-file", type=str,
                        help="Fichier WAV a traiter")

    args = parser.parse_args()

    success = True

    try:
        success &= test_audio_processing()
        success &= test_presets()
        success &= test_half_duplex()

        print("\n" + "=" * 60)
        if success:
            print("TOUS LES TESTS REUSSIS")
        else:
            print("CERTAINS TESTS ONT ECHOUE")
        print("=" * 60)

    except Exception as e:
        print(f"\nERREUR: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
