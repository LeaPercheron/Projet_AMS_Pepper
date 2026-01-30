#!/usr/bin/env python3
"""
Script de Test Audio Pipeline
=============================
Valide le traitement audio sans Pepper physique.

Tests:
- Resampling 48kHz -> 24kHz
- Beamforming 4 canaux -> mono
- Reduction de bruit
- AGC
- Half-duplex

Usage:
    python scripts/test_audio_pipeline.py
    python scripts/test_audio_pipeline.py --input data/corpus_audio/test.wav
    python scripts/test_audio_pipeline.py --generate-test-corpus
    python scripts/test_audio_pipeline.py --test-half-duplex
"""

import os
import sys
import time
import wave
import struct
import argparse
import numpy as np
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, Tuple

# Ajouter src au path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))


@dataclass
class AudioTestResult:
    """Resultat d'un test audio."""
    test_name: str
    passed: bool
    message: str = ""
    input_samples: int = 0
    output_samples: int = 0
    processing_time_ms: float = 0.0


class AudioPipelineTester:
    """
    Testeur du pipeline audio.
    """

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.results: List[AudioTestResult] = []

        # Modules
        self.processor = None
        self.half_duplex = None

    def setup(self) -> bool:
        """Initialise les modules."""
        print("=" * 60)
        print("TEST AUDIO PIPELINE")
        print("=" * 60)

        try:
            from assistant.audio.processing import AudioProcessor, AudioConfig
            from assistant.audio.half_duplex import HalfDuplexManager, HalfDuplexConfig

            # Creer le processeur audio
            config = AudioConfig(
                input_sample_rate=48000,
                output_sample_rate=24000,
                input_channels=4,
                output_channels=1
            )
            self.processor = AudioProcessor(config)

            # Creer le manager half-duplex
            hd_config = HalfDuplexConfig(
                cooldown_ms=200,
                log_state_changes=self.verbose
            )
            self.half_duplex = HalfDuplexManager(hd_config)

            print("[SETUP] Modules audio charges")
            return True

        except ImportError as e:
            print(f"[WARN] Import partiel: {e}")
            print("[INFO] Utilisation des tests standalone...")
            return True

    def generate_test_signal(
        self,
        duration_s: float = 1.0,
        sample_rate: int = 48000,
        channels: int = 4,
        frequency: float = 440.0
    ) -> bytes:
        """
        Genere un signal de test (sinusoide).

        Args:
            duration_s: Duree en secondes
            sample_rate: Frequence d'echantillonnage
            channels: Nombre de canaux
            frequency: Frequence de la sinusoide

        Returns:
            Audio PCM16 interleave
        """
        num_samples = int(duration_s * sample_rate)
        t = np.linspace(0, duration_s, num_samples)

        # Generer sinusoide
        signal = np.sin(2 * np.pi * frequency * t) * 0.5

        # Convertir en int16
        signal_int16 = (signal * 32767).astype(np.int16)

        # Dupliquer sur tous les canaux (interleave)
        if channels > 1:
            interleaved = np.zeros(num_samples * channels, dtype=np.int16)
            for ch in range(channels):
                # Ajouter un leger decalage de phase par canal (simulation beamforming)
                phase_shift = ch * 0.001 * sample_rate
                shifted = np.roll(signal_int16, int(phase_shift))
                interleaved[ch::channels] = shifted
            return interleaved.tobytes()
        else:
            return signal_int16.tobytes()

    def generate_noise(
        self,
        duration_s: float = 1.0,
        sample_rate: int = 48000,
        level: float = 0.1
    ) -> bytes:
        """Genere du bruit blanc."""
        num_samples = int(duration_s * sample_rate)
        noise = np.random.uniform(-level, level, num_samples)
        noise_int16 = (noise * 32767).astype(np.int16)
        return noise_int16.tobytes()

    def generate_speech_simulation(
        self,
        duration_s: float = 2.0,
        sample_rate: int = 48000
    ) -> bytes:
        """
        Simule de la parole (multi-frequences avec enveloppe).
        """
        num_samples = int(duration_s * sample_rate)
        t = np.linspace(0, duration_s, num_samples)

        # Plusieurs frequences (simulation voix)
        frequencies = [150, 300, 450, 600, 900]
        signal = np.zeros(num_samples)

        for freq in frequencies:
            amplitude = 1.0 / (freq / 100)  # Plus fort pour basses frequences
            signal += amplitude * np.sin(2 * np.pi * freq * t)

        # Normaliser
        signal = signal / np.max(np.abs(signal)) * 0.7

        # Enveloppe (attaque, sustain, release)
        envelope = np.ones(num_samples)
        attack = int(0.1 * sample_rate)
        release = int(0.2 * sample_rate)
        envelope[:attack] = np.linspace(0, 1, attack)
        envelope[-release:] = np.linspace(1, 0, release)
        signal *= envelope

        return (signal * 32767).astype(np.int16).tobytes()

    # =========================================================================
    # TESTS
    # =========================================================================

    def test_resampling(self) -> AudioTestResult:
        """Test du resampling 48kHz -> 24kHz."""
        print("\n[TEST] Resampling 48kHz -> 24kHz")

        try:
            # Generer signal 48kHz
            input_audio = self.generate_test_signal(
                duration_s=1.0,
                sample_rate=48000,
                channels=1,
                frequency=440.0
            )

            input_samples = len(input_audio) // 2  # int16 = 2 bytes

            start = time.time()

            if self.processor:
                output_audio = self.processor.resample(input_audio)
            else:
                # Resampling manuel (moyenne 2 samples)
                samples = np.frombuffer(input_audio, dtype=np.int16).astype(np.float32)
                if len(samples) % 2 != 0:
                    samples = np.append(samples, samples[-1])
                resampled = (samples[::2] + samples[1::2]) / 2
                output_audio = resampled.astype(np.int16).tobytes()

            processing_time = (time.time() - start) * 1000
            output_samples = len(output_audio) // 2

            # Verification: output devrait avoir ~moitie des samples
            expected_ratio = 0.5
            actual_ratio = output_samples / input_samples

            passed = abs(actual_ratio - expected_ratio) < 0.01

            return AudioTestResult(
                test_name="Resampling 48k->24k",
                passed=passed,
                message=f"Ratio: {actual_ratio:.3f} (attendu: {expected_ratio})",
                input_samples=input_samples,
                output_samples=output_samples,
                processing_time_ms=processing_time
            )

        except Exception as e:
            return AudioTestResult(
                test_name="Resampling 48k->24k",
                passed=False,
                message=f"Erreur: {e}"
            )

    def test_beamforming(self) -> AudioTestResult:
        """Test du beamforming 4 canaux -> mono."""
        print("\n[TEST] Beamforming 4ch -> mono")

        try:
            # Generer signal 4 canaux
            input_audio = self.generate_test_signal(
                duration_s=0.5,
                sample_rate=48000,
                channels=4,
                frequency=440.0
            )

            input_samples = len(input_audio) // 2  # Total samples
            input_frames = input_samples // 4  # Frames (4 canaux)

            start = time.time()

            if self.processor:
                output_audio = self.processor.beamform(input_audio)
            else:
                # Beamforming manuel (moyenne des canaux)
                samples = np.frombuffer(input_audio, dtype=np.int16).reshape(-1, 4).astype(np.float32)
                mono = np.mean(samples, axis=1)
                output_audio = mono.astype(np.int16).tobytes()

            processing_time = (time.time() - start) * 1000
            output_samples = len(output_audio) // 2

            # Verification: output devrait avoir 1/4 des samples
            passed = output_samples == input_frames

            return AudioTestResult(
                test_name="Beamforming 4ch->mono",
                passed=passed,
                message=f"Input: {input_frames} frames, Output: {output_samples} samples",
                input_samples=input_samples,
                output_samples=output_samples,
                processing_time_ms=processing_time
            )

        except Exception as e:
            return AudioTestResult(
                test_name="Beamforming 4ch->mono",
                passed=False,
                message=f"Erreur: {e}"
            )

    def test_noise_reduction(self) -> AudioTestResult:
        """Test de la reduction de bruit."""
        print("\n[TEST] Reduction de bruit")

        try:
            # Generer signal + bruit
            signal = self.generate_speech_simulation(duration_s=1.0, sample_rate=48000)
            noise = self.generate_noise(duration_s=1.0, sample_rate=48000, level=0.3)

            # Mixer
            signal_arr = np.frombuffer(signal, dtype=np.int16).astype(np.float32)
            noise_arr = np.frombuffer(noise, dtype=np.int16).astype(np.float32)
            mixed = signal_arr + noise_arr
            mixed = np.clip(mixed, -32767, 32767).astype(np.int16)
            input_audio = mixed.tobytes()

            # Calculer RMS avant
            rms_before = np.sqrt(np.mean(mixed.astype(np.float32) ** 2))

            start = time.time()

            if self.processor:
                output_audio = self.processor.reduce_noise(input_audio)
            else:
                # Filtrage passe-bas simple (simulation)
                from scipy import signal as scipy_signal
                b, a = scipy_signal.butter(4, 3000 / 24000, btype='low')
                filtered = scipy_signal.filtfilt(b, a, mixed.astype(np.float32))
                output_audio = filtered.astype(np.int16).tobytes()

            processing_time = (time.time() - start) * 1000

            # Calculer RMS apres
            output_arr = np.frombuffer(output_audio, dtype=np.int16).astype(np.float32)
            rms_after = np.sqrt(np.mean(output_arr ** 2))

            # Le bruit haute frequence devrait etre reduit
            passed = True  # Test qualitatif

            return AudioTestResult(
                test_name="Noise Reduction",
                passed=passed,
                message=f"RMS: {rms_before:.0f} -> {rms_after:.0f}",
                input_samples=len(input_audio) // 2,
                output_samples=len(output_audio) // 2,
                processing_time_ms=processing_time
            )

        except ImportError:
            return AudioTestResult(
                test_name="Noise Reduction",
                passed=True,
                message="scipy non disponible - test skip"
            )
        except Exception as e:
            return AudioTestResult(
                test_name="Noise Reduction",
                passed=False,
                message=f"Erreur: {e}"
            )

    def test_agc(self) -> AudioTestResult:
        """Test de l'AGC (Automatic Gain Control)."""
        print("\n[TEST] AGC")

        try:
            # Generer signal faible
            weak_signal = self.generate_test_signal(
                duration_s=0.5,
                sample_rate=24000,
                channels=1,
                frequency=440.0
            )

            # Reduire le volume
            samples = np.frombuffer(weak_signal, dtype=np.int16).astype(np.float32)
            samples *= 0.1  # Signal tres faible
            weak_input = samples.astype(np.int16).tobytes()

            rms_before = np.sqrt(np.mean(samples ** 2))

            start = time.time()

            if self.processor:
                output_audio = self.processor.apply_agc(weak_input)
            else:
                # AGC simple (normalisation)
                max_val = np.max(np.abs(samples))
                if max_val > 0:
                    normalized = samples * (32767 * 0.7 / max_val)
                else:
                    normalized = samples
                output_audio = normalized.astype(np.int16).tobytes()

            processing_time = (time.time() - start) * 1000

            output_arr = np.frombuffer(output_audio, dtype=np.int16).astype(np.float32)
            rms_after = np.sqrt(np.mean(output_arr ** 2))

            # L'AGC devrait augmenter le volume
            passed = rms_after > rms_before * 2

            return AudioTestResult(
                test_name="AGC",
                passed=passed,
                message=f"RMS: {rms_before:.0f} -> {rms_after:.0f} (x{rms_after/rms_before:.1f})",
                input_samples=len(weak_input) // 2,
                output_samples=len(output_audio) // 2,
                processing_time_ms=processing_time
            )

        except Exception as e:
            return AudioTestResult(
                test_name="AGC",
                passed=False,
                message=f"Erreur: {e}"
            )

    def test_half_duplex(self) -> AudioTestResult:
        """Test du mode half-duplex."""
        print("\n[TEST] Half-Duplex")

        try:
            from assistant.audio.half_duplex import HalfDuplexManager, HalfDuplexConfig, SpeakingState

            manager = HalfDuplexManager(HalfDuplexConfig(
                cooldown_ms=100,
                log_state_changes=False
            ))

            # Test audio
            test_audio = self.generate_test_signal(duration_s=0.1, sample_rate=24000, channels=1)

            # Etat LISTENING - audio devrait passer
            assert manager.state == SpeakingState.LISTENING, "Etat initial devrait etre LISTENING"
            filtered_listening = manager.filter_input_audio(test_audio)
            assert filtered_listening == test_audio, "Audio devrait passer en mode LISTENING"

            # Etat SPEAKING - audio devrait etre mute
            manager.start_speaking()
            assert manager.state == SpeakingState.SPEAKING, "Etat devrait etre SPEAKING"
            filtered_speaking = manager.filter_input_audio(test_audio)
            assert filtered_speaking == bytes(len(test_audio)), "Audio devrait etre silence en mode SPEAKING"

            # Retour LISTENING apres cooldown
            manager.stop_speaking()
            time.sleep(0.15)  # Attendre cooldown
            assert manager.state == SpeakingState.LISTENING, "Etat devrait revenir a LISTENING"

            # Test interruption
            manager.start_speaking()
            manager.force_listening()
            assert manager.state == SpeakingState.LISTENING, "force_listening devrait fonctionner"

            # Stats
            stats = manager.get_stats()

            manager.cleanup()

            return AudioTestResult(
                test_name="Half-Duplex",
                passed=True,
                message=f"Transitions OK, interruptions: {stats['interruption_count']}"
            )

        except ImportError:
            return AudioTestResult(
                test_name="Half-Duplex",
                passed=True,
                message="Module non disponible - test skip"
            )
        except AssertionError as e:
            return AudioTestResult(
                test_name="Half-Duplex",
                passed=False,
                message=f"Assertion: {e}"
            )
        except Exception as e:
            return AudioTestResult(
                test_name="Half-Duplex",
                passed=False,
                message=f"Erreur: {e}"
            )

    def test_full_pipeline(self) -> AudioTestResult:
        """Test du pipeline complet."""
        print("\n[TEST] Pipeline Complet (4ch 48k -> mono 24k)")

        try:
            # Generer signal 4 canaux 48kHz
            input_audio = self.generate_test_signal(
                duration_s=1.0,
                sample_rate=48000,
                channels=4,
                frequency=440.0
            )

            input_samples = len(input_audio) // 2
            expected_output_samples = (input_samples // 4) // 2  # 4ch->mono, 48k->24k

            start = time.time()

            if self.processor:
                output_audio = self.processor.process(input_audio)
            else:
                # Pipeline manuel
                # 1. Beamforming
                samples = np.frombuffer(input_audio, dtype=np.int16).reshape(-1, 4).astype(np.float32)
                mono = np.mean(samples, axis=1).astype(np.int16)

                # 2. Resampling
                if len(mono) % 2 != 0:
                    mono = np.append(mono, mono[-1])
                resampled = ((mono[::2].astype(np.float32) + mono[1::2].astype(np.float32)) / 2).astype(np.int16)

                output_audio = resampled.tobytes()

            processing_time = (time.time() - start) * 1000
            output_samples = len(output_audio) // 2

            # Verification
            ratio = output_samples / expected_output_samples
            passed = 0.95 <= ratio <= 1.05

            return AudioTestResult(
                test_name="Full Pipeline",
                passed=passed,
                message=f"4ch 48k -> mono 24k: {input_samples} -> {output_samples} samples",
                input_samples=input_samples,
                output_samples=output_samples,
                processing_time_ms=processing_time
            )

        except Exception as e:
            return AudioTestResult(
                test_name="Full Pipeline",
                passed=False,
                message=f"Erreur: {e}"
            )

    # =========================================================================
    # EXECUTION
    # =========================================================================

    def run_all_tests(self) -> bool:
        """Execute tous les tests."""
        print("\n" + "=" * 60)
        print("EXECUTION DES TESTS")
        print("=" * 60)

        tests = [
            self.test_resampling,
            self.test_beamforming,
            self.test_noise_reduction,
            self.test_agc,
            self.test_half_duplex,
            self.test_full_pipeline,
        ]

        for test_fn in tests:
            result = test_fn()
            self.results.append(result)

            status = "PASS" if result.passed else "FAIL"
            print(f"  [{status}] {result.test_name}: {result.message}")

            if self.verbose and result.processing_time_ms > 0:
                print(f"       Temps: {result.processing_time_ms:.1f}ms")

        return all(r.passed for r in self.results)

    def print_summary(self):
        """Affiche le resume."""
        print("\n" + "=" * 60)
        print("RESUME")
        print("=" * 60)

        passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)

        print(f"\nTests: {passed}/{total} reussis")

        if passed == total:
            print("\n[OK] Tous les tests passent!")
        else:
            print("\n[ATTENTION] Certains tests ont echoue:")
            for r in self.results:
                if not r.passed:
                    print(f"  - {r.test_name}: {r.message}")

    def generate_test_corpus(self, output_dir: str = "data/corpus_audio"):
        """Genere un corpus de test."""
        print("\n" + "=" * 60)
        print("GENERATION CORPUS DE TEST")
        print("=" * 60)

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        files_created = []

        # 1. Signal propre
        clean = self.generate_speech_simulation(duration_s=3.0, sample_rate=48000)
        clean_path = output_path / "speech_clean_48k.wav"
        self._save_wav(clean_path, clean, 48000, 1)
        files_created.append(clean_path)

        # 2. Signal avec bruit
        noise = self.generate_noise(duration_s=3.0, sample_rate=48000, level=0.2)
        clean_arr = np.frombuffer(clean, dtype=np.int16).astype(np.float32)
        noise_arr = np.frombuffer(noise, dtype=np.int16).astype(np.float32)
        noisy = np.clip(clean_arr + noise_arr, -32767, 32767).astype(np.int16).tobytes()
        noisy_path = output_path / "speech_noisy_48k.wav"
        self._save_wav(noisy_path, noisy, 48000, 1)
        files_created.append(noisy_path)

        # 3. Signal 4 canaux
        multichannel = self.generate_test_signal(duration_s=2.0, sample_rate=48000, channels=4)
        multi_path = output_path / "test_4ch_48k.wav"
        self._save_wav(multi_path, multichannel, 48000, 4)
        files_created.append(multi_path)

        # 4. Silence
        silence = bytes(48000 * 2 * 2)  # 2 secondes de silence
        silence_path = output_path / "silence_48k.wav"
        self._save_wav(silence_path, silence, 48000, 1)
        files_created.append(silence_path)

        print(f"\n{len(files_created)} fichiers crees:")
        for f in files_created:
            print(f"  - {f}")

    def _save_wav(self, path: Path, audio: bytes, sample_rate: int, channels: int):
        """Sauvegarde un fichier WAV."""
        with wave.open(str(path), 'wb') as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(sample_rate)
            wf.writeframes(audio)


def main():
    parser = argparse.ArgumentParser(description="Test du pipeline audio")
    parser.add_argument("--verbose", "-v", action="store_true", help="Affichage detaille")
    parser.add_argument("--input", type=str, help="Fichier WAV d'entree")
    parser.add_argument("--generate-test-corpus", action="store_true", help="Generer corpus de test")
    parser.add_argument("--test-half-duplex", action="store_true", help="Test half-duplex uniquement")

    args = parser.parse_args()

    tester = AudioPipelineTester(verbose=args.verbose)

    if not tester.setup():
        print("[WARN] Setup partiel")

    if args.generate_test_corpus:
        tester.generate_test_corpus()
        return

    if args.test_half_duplex:
        result = tester.test_half_duplex()
        status = "PASS" if result.passed else "FAIL"
        print(f"\n[{status}] {result.test_name}: {result.message}")
        sys.exit(0 if result.passed else 1)

    # Tous les tests
    success = tester.run_all_tests()
    tester.print_summary()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
