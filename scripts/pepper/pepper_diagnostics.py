#!/usr/bin/env python3
# Diagnostics Pepper (Pepper seul)

from __future__ import annotations

import argparse
import math
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple


# Configs/constantes NAOqi
CAMERA_RESOLUTIONS = {
    1: (160, 120),
    2: (320, 240),
    3: (640, 480),
    4: (1280, 960),
}
COLOR_SPACE_RGB = 11  # kRGBColorSpace (NAOqi)


@dataclass
class TestResult:
    name: str
    passed: bool
    message: str = ""


def _safe_call(label: str, fn: Callable[[], None]) -> TestResult:
    # Gere call.
    try:
        fn()
        return TestResult(label, True, "OK")
    except Exception as e:
        return TestResult(label, False, f"Erreur: {e}")


def _print_header(title: str) -> None:
    # Gere header.
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


# A1: Ping + NAOqi
def test_ping(ip: str, count: int = 4) -> TestResult:
    # Gere ping.
    def _run():
        # Execute l'action.
        print(f"[PING] {ip} ({count} paquets)")
        result = subprocess.run(
            ["ping", "-c", str(count), ip],
            capture_output=True,
            text=True,
            check=False
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "ping failed")
        print(result.stdout.strip())

    return _safe_call("A1.Ping", _run)


def test_naoqi_connect(ip: str, port: int) -> Tuple[TestResult, Optional[object]]:
    # Gere naoqi connect.
    session = None

    def _run():
        # Execute l'action.
        nonlocal session
        try:
            import qi
        except ImportError as e:
            raise RuntimeError("SDK qi non disponible") from e

        print(f"[NAOqi] Connexion tcp://{ip}:{port}")
        session = qi.Session()
        session.connect(f"tcp://{ip}:{port}")

        # Appel simple pour valider
        memory = session.service("ALMemory")
        _ = memory.getData("RobotConfig/Body/Type")
        print("[NAOqi] Service ALMemory OK")

    result = _safe_call("A1.NAOqi", _run)
    if not result.passed:
        session = None
    return result, session


def test_list_services(session) -> TestResult:
    # Gere list services.
    def _run():
        # Execute l'action.
        services = []
        if hasattr(session, "services"):
            services = session.services()
        else:
            svc_mgr = session.service("ALServiceManager")
            services = svc_mgr.services()

        print(f"[NAOqi] {len(services)} services détectés")
        # Afficher un extrait pour debug
        for name in sorted(services)[:15]:
            print(f"  - {name}")

    return _safe_call("A1.Services", _run)


# A2: Caméra
def test_camera_capture(session, output_dir: Path, resolution: int = 3, camera_id: int = 0) -> TestResult:
    # Gere camera capture.
    def _run():
        # Execute l'action.
        video = session.service("ALVideoDevice")
        width, height = CAMERA_RESOLUTIONS.get(resolution, (640, 480))
        client_name = "pepper_diag_cam"

        print(f"[CAM] Subscribe {width}x{height} camera={camera_id}")
        handle = video.subscribeCamera(
            client_name,
            camera_id,
            resolution,
            COLOR_SPACE_RGB,
            10
        )

        try:
            image = video.getImageRemote(handle)
        finally:
            video.unsubscribe(handle)

        if not image or len(image) < 7:
            raise RuntimeError("Image invalide")

        img_width = image[0]
        img_height = image[1]
        img_data = image[6]

        if isinstance(img_data, (list, tuple)):
            img_bytes = bytes(img_data)
        else:
            img_bytes = bytes(img_data)

        if len(img_bytes) < img_width * img_height * 3:
            raise RuntimeError("Buffer image incomplet")

        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / "pepper_cam_test.ppm"
        with open(out_path, "wb") as f:
            f.write(f"P6\n{img_width} {img_height}\n255\n".encode("ascii"))
            f.write(img_bytes[: img_width * img_height * 3])

        print(f"[CAM] Image sauvegardée: {out_path}")

    return _safe_call("A2.Camera", _run)


# A3: Micro 4 canaux (ALAudioRecorder)
def test_audio_record(session, output_dir: Path, duration_s: float = 5.0) -> TestResult:
    # Gere audio record.
    def _run():
        # Execute l'action.
        recorder = session.service("ALAudioRecorder")
        file_path = "/home/nao/pepper_diag_audio.wav"
        sample_rate = 48000
        channels = [1, 1, 1, 1]  # 4 canaux

        print(f"[MIC] Enregistrement {duration_s:.1f}s -> {file_path}")
        try:
            recorder.startMicrophonesRecording(file_path, "wav", sample_rate, channels)
        except Exception as e:
            raise RuntimeError(f"startMicrophonesRecording a échoué: {e}")

        time.sleep(duration_s)
        recorder.stopMicrophonesRecording()

        # Vérifier existence/tailles si possible
        file_mgr = None
        try:
            file_mgr = session.service("ALFileManager")
        except Exception:
            file_mgr = None

        if file_mgr and hasattr(file_mgr, "fileExists"):
            exists = file_mgr.fileExists(file_path)
            if not exists:
                raise RuntimeError("Fichier WAV non trouvé sur Pepper")

        if file_mgr and hasattr(file_mgr, "getFile"):
            output_dir.mkdir(parents=True, exist_ok=True)
            data = file_mgr.getFile(file_path)
            out_path = output_dir / "pepper_mic_test.wav"
            with open(out_path, "wb") as f:
                f.write(bytes(data))
            size = out_path.stat().st_size
            print(f"[MIC] WAV téléchargé: {out_path} ({size} bytes)")
        else:
            print("[MIC] WAV enregistré sur Pepper (non téléchargé)")

    return _safe_call("A3.Micro", _run)


# A4: Sortie audio (streaming)
def _generate_sine_pcm16(freq_hz: float, duration_s: float, sample_rate: int) -> bytes:
    # Gere sine pcm16.
    samples = int(sample_rate * duration_s)
    pcm = bytearray()
    for n in range(samples):
        val = int(math.sin(2.0 * math.pi * freq_hz * (n / sample_rate)) * 0.3 * 32767)
        pcm += int(val).to_bytes(2, byteorder="little", signed=True)
    return bytes(pcm)


def test_audio_output(session, duration_s: float = 1.5, sample_rate: int = 16000) -> TestResult:
    # Gere audio output.
    def _run():
        # Execute l'action.
        audio = session.service("ALAudioDevice")
        pcm = _generate_sine_pcm16(440.0, duration_s, sample_rate)
        channels = 1

        print("[AUDIO] Tentative streaming sendRemoteBufferToOutput...")
        attempts = [
            (pcm, channels, sample_rate),
            (channels, sample_rate, pcm),
            (sample_rate, channels, pcm),
            (sample_rate, pcm, channels),
        ]

        for args in attempts:
            try:
                audio.sendRemoteBufferToOutput(*args)
                print("[AUDIO] Streaming OK")
                return
            except Exception:
                continue

        # Fallback si streaming indisponible
        try:
            player = session.service("ALAudioPlayer")
            print("[AUDIO] Fallback: ALAudioPlayer.playSine")
            player.playSine(440.0, 0.6, 0.0, duration_s)
        except Exception as e:
            raise RuntimeError(f"Streaming indisponible et fallback échoué: {e}")

    return _safe_call("A4.AudioOut", _run)


# A5: Tablette
def test_tablet(session, url: str, display_s: float = 5.0) -> TestResult:
    # Gere tablet.
    def _run():
        # Execute l'action.
        tablet = session.service("ALTabletService")
        print(f"[TABLET] Affichage {url}")
        tablet.showWebview(url)
        time.sleep(display_s)
        tablet.hideWebview()
        print("[TABLET] OK")

    return _safe_call("A5.Tablet", _run)


# A6: LEDs
def test_leds(session) -> TestResult:
    # Gere leds.
    def _run():
        # Execute l'action.
        leds = session.service("ALLeds")
        colors = {
            "violet": 0x7F00FF,
            "bleu": 0x0000FF,
            "vert": 0x00FF00,
            "blanc": 0xFFFFFF,
            "orange": 0xFF8000,
        }
        print("[LEDS] Séquence couleurs")
        for name, rgb in colors.items():
            print(f"  - {name}")
            leds.fadeRGB("FaceLeds", rgb, 0.8)
            time.sleep(0.5)

    return _safe_call("A6.LEDs", _run)


# A7: setFileAsInput
def test_set_file_as_input(session, pepper_wav_path: str) -> TestResult:
    # Gere set file as input.
    def _run():
        # Execute l'action.
        audio = session.service("ALAudioDevice")
        print(f"[AUDIO] setFileAsInput: {pepper_wav_path}")
        audio.setFileAsInput(pepper_wav_path)
        time.sleep(1.0)

    return _safe_call("A7.SetFileAsInput", _run)


# Main
def main() -> int:
    # Gere l'action.
    parser = argparse.ArgumentParser(description="Diagnostics Pepper (Pepper seul)")
    parser.add_argument("--pepper-ip", required=True, help="IP du robot Pepper")
    parser.add_argument("--pepper-port", type=int, default=9559, help="Port NAOqi (defaut: 9559)")
    parser.add_argument("--output-dir", type=str, default="logs/pepper_diagnostics", help="Dossier sortie")
    parser.add_argument("--audio-duration", type=float, default=5.0, help="Durée enregistrement micro")
    parser.add_argument("--tablet-url", type=str, default="http://localhost:8765", help="URL test tablette")
    parser.add_argument("--camera-resolution", type=int, default=3, choices=sorted(CAMERA_RESOLUTIONS.keys()))
    parser.add_argument("--skip-ping", action="store_true")
    parser.add_argument("--skip-camera", action="store_true")
    parser.add_argument("--skip-audio-in", action="store_true")
    parser.add_argument("--skip-audio-out", action="store_true")
    parser.add_argument("--skip-tablet", action="store_true")
    parser.add_argument("--skip-leds", action="store_true")
    parser.add_argument("--set-file-as-input", type=str, default="", help="Chemin WAV sur Pepper (A7)")

    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    results: List[TestResult] = []

    _print_header("PEPPER DIAGNOSTICS - PEPPER SEUL")

    if not args.skip_ping:
        results.append(test_ping(args.pepper_ip))

    naoqi_result, session = test_naoqi_connect(args.pepper_ip, args.pepper_port)
    results.append(naoqi_result)
    if session is None:
        _print_header("RESUME")
        _print_summary(results)
        return 1

    results.append(test_list_services(session))

    if not args.skip_camera:
        results.append(test_camera_capture(session, output_dir, args.camera_resolution))

    if not args.skip_audio_in:
        results.append(test_audio_record(session, output_dir, args.audio_duration))

    if not args.skip_audio_out:
        results.append(test_audio_output(session))

    if not args.skip_tablet:
        results.append(test_tablet(session, args.tablet_url))

    if not args.skip_leds:
        results.append(test_leds(session))

    if args.set_file_as_input:
        results.append(test_set_file_as_input(session, args.set_file_as_input))

    _print_header("RESUME")
    _print_summary(results)
    return 0 if all(r.passed for r in results) else 1


def _print_summary(results: List[TestResult]) -> None:
    # Gere summary.
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    print(f"Tests: {passed}/{total} reussis")
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(f"  [{status}] {r.name}: {r.message}")


if __name__ == "__main__":
    sys.exit(main())
