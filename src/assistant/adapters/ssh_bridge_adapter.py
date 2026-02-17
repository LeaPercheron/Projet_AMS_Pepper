# Adaptateur Pepper via SSH (fallback sans qi local)

import base64
import io
import json
import re
import subprocess
import threading
import time
import wave
from typing import Callable, Optional

from .base import AdapterConfig, LEDColor, RobotAdapter


class SSHBridgeAdapter(RobotAdapter):
    # Fallback: exécute des commandes Python+qi sur Pepper via SSH.

    def __init__(
        self,
        ip: str,
        port: int = 9559,
        ssh_user: str = "nao",
        ssh_port: int = 22,
        ssh_python: str = "python",
        config: Optional[AdapterConfig] = None
    ):
        super().__init__(config)
        self.ip = ip
        self.port = port
        self.ssh_user = ssh_user
        self.ssh_port = ssh_port
        self.ssh_python = ssh_python

        self._is_capturing = False
        self._is_streaming_video = False
        self._audio_callback: Optional[Callable[[bytes], None]] = None
        self._video_callback: Optional[Callable[[bytes], None]] = None
        self._capture_thread: Optional[threading.Thread] = None
        self._video_thread: Optional[threading.Thread] = None
        self._playback_thread: Optional[threading.Thread] = None
        self._playback_running = False
        self._playback_buffer = bytearray()
        self._playback_lock = threading.Lock()

        self._audio_frames_sent = 0
        self._audio_frames_received = 0
        self._video_frames_sent = 0
        self._head_frozen = False

    # CONNEXION

    def _ssh_base_command(self) -> list:
        return [
            "ssh",
            "-p",
            str(self.ssh_port),
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=5",
            "-o",
            "StrictHostKeyChecking=accept-new",
            f"{self.ssh_user}@{self.ip}",
        ]

    def _run_remote_python(self, code: str, timeout: float = 8.0):
        cmd = self._ssh_base_command() + [self.ssh_python, "-"]
        try:
            result = subprocess.run(
                cmd,
                input=code.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=False
            )
        except Exception as e:
            return False, "", str(e)

        stdout = result.stdout.decode("utf-8", errors="ignore").strip()
        stderr = result.stderr.decode("utf-8", errors="ignore").strip()
        if result.returncode != 0:
            return False, stdout, stderr or f"exit code {result.returncode}"
        return True, stdout, stderr

    def _build_qi_code(self, body: str) -> str:
        return (
            "import qi\n"
            f"s=qi.Session(); s.connect('tcp://127.0.0.1:{self.port}')\n"
            f"{body}\n"
        )

    @staticmethod
    def _last_non_empty_line(text: str) -> str:
        for line in reversed(text.splitlines()):
            line = line.strip()
            if line:
                return line
        return ""

    @staticmethod
    def _extract_base64(text: str) -> str:
        pattern = re.compile(r"^[A-Za-z0-9+/=]+$")
        for line in reversed(text.splitlines()):
            token = line.strip()
            if token and pattern.match(token):
                return token
        return ""

    def connect(self) -> bool:
        body = (
            "memory=s.service('ALMemory')\n"
            "memory.getData('RobotConfig/Body/Type')\n"
            "print('OK')"
        )
        ok, stdout, err = self._run_remote_python(self._build_qi_code(body), timeout=10.0)
        if ok and "OK" in stdout:
            self._is_connected = True
            print(f"[SSHBridge] Connecte via SSH sur {self.ssh_user}@{self.ip}")
            return True

        self._is_connected = False
        print(f"[SSHBridge] Echec connexion: {err or stdout}")
        return False

    def disconnect(self):
        self.unfreeze_head()
        self.stop_audio_capture()
        self.stop_audio_playback()
        self.stop_video_stream()
        self._is_connected = False
        print("[SSHBridge] Deconnecte")

    # AUDIO

    def start_audio_capture(self, callback: Callable[[bytes], None]) -> bool:
        if not self._is_connected:
            return False
        if self._is_capturing:
            return True

        self._audio_callback = callback
        self._is_capturing = True
        self._capture_thread = threading.Thread(target=self._audio_capture_loop, daemon=True)
        self._capture_thread.start()
        print("[SSHBridge] Capture audio demarree")
        return True

    def _audio_capture_loop(self):
        while self._is_capturing:
            try:
                wav_bytes = self._capture_audio_chunk_wav(duration_s=0.6)
                if not wav_bytes:
                    time.sleep(0.2)
                    continue

                pcm_bytes = self._wav_to_pcm(wav_bytes)
                if pcm_bytes and self._audio_callback:
                    self._audio_callback(pcm_bytes)
                    self._audio_frames_sent += 1
            except Exception as e:
                print(f"[SSHBridge] Erreur capture audio: {e}")
                time.sleep(0.3)

    def _capture_audio_chunk_wav(self, duration_s: float = 0.6) -> bytes:
        body = (
            "import base64, time\n"
            "rec=s.service('ALAudioRecorder')\n"
            "path='/tmp/pepper_bridge_chunk.wav'\n"
            "rec.startMicrophonesRecording(path, 'wav', 48000, [1,1,1,1])\n"
            f"time.sleep({max(0.2, float(duration_s))})\n"
            "rec.stopMicrophonesRecording()\n"
            "with open(path, 'rb') as f:\n"
            "    data=f.read()\n"
            "print(base64.b64encode(data).decode('ascii'))"
        )
        ok, stdout, _ = self._run_remote_python(self._build_qi_code(body), timeout=12.0)
        if not ok:
            return b""
        b64 = self._extract_base64(stdout)
        if not b64:
            return b""
        try:
            return base64.b64decode(b64)
        except Exception:
            return b""

    @staticmethod
    def _wav_to_pcm(wav_bytes: bytes) -> bytes:
        try:
            with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                return wf.readframes(wf.getnframes())
        except Exception:
            return b""

    def stop_audio_capture(self):
        self._is_capturing = False
        if self._capture_thread:
            self._capture_thread.join(timeout=2.0)
            self._capture_thread = None
        print("[SSHBridge] Capture audio arretee")

    def play_audio(self, audio_bytes: bytes) -> bool:
        if not self._is_connected:
            return False
        if not audio_bytes:
            return True

        with self._playback_lock:
            self._playback_buffer.extend(audio_bytes)

        if not self._playback_running:
            self._playback_running = True
            self._playback_thread = threading.Thread(target=self._playback_loop, daemon=True)
            self._playback_thread.start()
        return True

    def _playback_loop(self):
        max_chunk = int(0.35 * self.config.sample_rate * self.config.channels_out * 2)
        while self._playback_running:
            chunk = b""
            with self._playback_lock:
                if self._playback_buffer:
                    n = min(len(self._playback_buffer), max_chunk)
                    chunk = bytes(self._playback_buffer[:n])
                    del self._playback_buffer[:n]
            if not chunk:
                time.sleep(0.05)
                continue

            try:
                if self._send_audio_chunk(chunk):
                    self._audio_frames_received += 1
            except Exception:
                pass
            time.sleep(0.03)

    def _send_audio_chunk(self, chunk: bytes) -> bool:
        payload = base64.b64encode(chunk).decode("ascii")
        body = (
            "import base64\n"
            f"audio=base64.b64decode('{payload}')\n"
            "audio_dev=s.service('ALAudioDevice')\n"
            "ok=False\n"
            "attempts=[(audio,2,48000),(2,48000,audio),(48000,2,audio),(48000,audio,2)]\n"
            "for args in attempts:\n"
            "    try:\n"
            "        audio_dev.sendRemoteBufferToOutput(*args)\n"
            "        ok=True\n"
            "        break\n"
            "    except Exception:\n"
            "        pass\n"
            "print('OK' if ok else 'FAIL')"
        )
        ok, stdout, _ = self._run_remote_python(self._build_qi_code(body), timeout=8.0)
        if not ok:
            return False
        return self._last_non_empty_line(stdout) == "OK"

    def stop_audio_playback(self):
        self._playback_running = False
        if self._playback_thread:
            self._playback_thread.join(timeout=2.0)
            self._playback_thread = None
        with self._playback_lock:
            self._playback_buffer.clear()
        print("[SSHBridge] Playback arrete")

    # LEDs

    def set_led_color(self, color: LEDColor, fade: bool = True):
        r, g, b = color.value
        self.set_led_rgb(r, g, b, fade=fade)

    def set_led_rgb(self, r: int, g: int, b: int, fade: bool = True):
        if not self._is_connected:
            return
        color_int = (int(r) << 16) | (int(g) << 8) | int(b)
        duration = self.config.led_fade_duration if fade else 0.0
        body = (
            "leds=s.service('ALLeds')\n"
            f"leds.fadeRGB('FaceLeds', {color_int}, {duration})\n"
            "print('OK')"
        )
        self._run_remote_python(self._build_qi_code(body), timeout=4.0)

    # CAMERA

    def capture_image(self) -> Optional[bytes]:
        if not self._is_connected:
            return None
        body = (
            "import base64\n"
            "video=s.service('ALVideoDevice')\n"
            "client=video.subscribeCamera('SSHBridgeCam', 0, 2, 11, 5)\n"
            "try:\n"
            "    image=video.getImageRemote(client)\n"
            "finally:\n"
            "    video.unsubscribe(client)\n"
            "if image and len(image) >= 7:\n"
            "    data=bytes(image[6])\n"
            "    print(base64.b64encode(data).decode('ascii'))\n"
            "else:\n"
            "    print('')"
        )
        ok, stdout, _ = self._run_remote_python(self._build_qi_code(body), timeout=8.0)
        if not ok:
            return None
        b64 = self._extract_base64(stdout)
        if not b64:
            return None
        try:
            return base64.b64decode(b64)
        except Exception:
            return None

    def start_video_stream(self, callback: Callable[[bytes], None]) -> bool:
        if not self._is_connected:
            return False
        if self._is_streaming_video:
            return True
        self._video_callback = callback
        self._is_streaming_video = True
        self._video_thread = threading.Thread(target=self._video_stream_loop, daemon=True)
        self._video_thread.start()
        print("[SSHBridge] Stream video demarre")
        return True

    def _video_stream_loop(self):
        while self._is_streaming_video:
            try:
                frame = self.capture_image()
                if frame and self._video_callback:
                    self._video_callback(frame)
                    self._video_frames_sent += 1
            except Exception:
                pass
            time.sleep(0.35)

    def stop_video_stream(self):
        self._is_streaming_video = False
        if self._video_thread:
            self._video_thread.join(timeout=2.0)
            self._video_thread = None
        print("[SSHBridge] Stream video arrete")

    # PAROLE

    def say(self, text: str, blocking: bool = False) -> bool:
        if not self._is_connected:
            return False
        payload = json.dumps(text, ensure_ascii=False)
        body = (
            "tts=s.service('ALTextToSpeech')\n"
            f"tts.say({payload})\n"
            "print('OK')"
        )
        ok, stdout, _ = self._run_remote_python(self._build_qi_code(body), timeout=12.0)
        if blocking:
            time.sleep(max(0.15, 0.08 * len(text.split())))
        return ok and self._last_non_empty_line(stdout) == "OK"

    def stop_speaking(self):
        if not self._is_connected:
            return
        body = "s.service('ALTextToSpeech').stopAll()\nprint('OK')"
        self._run_remote_python(self._build_qi_code(body), timeout=4.0)

    # DETECTION PRESENCE

    def is_person_present(self) -> bool:
        if not self._is_connected:
            return False
        body = (
            "faces=s.service('ALMemory').getData('FaceDetected')\n"
            "present = bool(faces) and (len(faces) > 0)\n"
            "print('1' if present else '0')"
        )
        ok, stdout, _ = self._run_remote_python(self._build_qi_code(body), timeout=4.0)
        if not ok:
            return False
        return self._last_non_empty_line(stdout) == "1"

    def get_person_distance(self) -> Optional[float]:
        if not self._is_connected:
            return None
        body = (
            "dist=s.service('ALMemory').getData('Device/SubDeviceList/Platform/Front/Sonar/Sensor/Value')\n"
            "print(dist if dist is not None else '')"
        )
        ok, stdout, _ = self._run_remote_python(self._build_qi_code(body), timeout=4.0)
        if not ok:
            return None
        line = self._last_non_empty_line(stdout)
        try:
            return float(line)
        except Exception:
            return None

    # TABLETTE

    def show_on_tablet(self, url: str) -> bool:
        if not self._is_connected:
            return False
        payload = json.dumps(url, ensure_ascii=False)
        body = (
            "tablet=s.service('ALTabletService')\n"
            f"tablet.showWebview({payload})\n"
            "print('OK')"
        )
        ok, stdout, _ = self._run_remote_python(self._build_qi_code(body), timeout=8.0)
        return ok and self._last_non_empty_line(stdout) == "OK"

    def hide_tablet(self):
        if not self._is_connected:
            return
        body = "s.service('ALTabletService').hideWebview()\nprint('OK')"
        self._run_remote_python(self._build_qi_code(body), timeout=4.0)

    # MOUVEMENTS (optionnels)

    def wave(self):
        if not self._is_connected:
            return
        body = (
            "motion=s.service('ALMotion')\n"
            "j=['RShoulderPitch','RShoulderRoll','RElbowYaw','RElbowRoll']\n"
            "a=[[1.2,0.9,1.2],[ -0.2,-0.5,-0.2],[1.5,1.2,1.5],[0.8,1.2,0.8]]\n"
            "t=[[0.4,0.8,1.2]]*4\n"
            "motion.angleInterpolation(j, a, t, True)\n"
            "print('OK')"
        )
        self._run_remote_python(self._build_qi_code(body), timeout=8.0)

    def nod(self):
        if not self._is_connected:
            return
        body = (
            "motion=s.service('ALMotion')\n"
            "motion.angleInterpolation(['HeadPitch'], [[0.2,-0.2,0.0]], [[0.3,0.6,0.9]], True)\n"
            "print('OK')"
        )
        self._run_remote_python(self._build_qi_code(body), timeout=5.0)

    def point_at_tablet(self):
        if not self._is_connected:
            return
        body = (
            "motion=s.service('ALMotion')\n"
            "motion.angleInterpolation(['RShoulderPitch','RShoulderRoll'], [[0.4],[ -0.7]], [[0.6],[0.6]], True)\n"
            "print('OK')"
        )
        self._run_remote_python(self._build_qi_code(body), timeout=5.0)

    def freeze_head(self):
        if not self._is_connected or self._head_frozen:
            return
        body = (
            "motion=s.service('ALMotion')\n"
            "try:\n"
            "    aware=s.service('ALBasicAwareness')\n"
            "    aware.setEnabled(False)\n"
            "except Exception:\n"
            "    pass\n"
            "motion.setStiffnesses('Head', 1.0)\n"
            "motion.setAngles(['HeadYaw','HeadPitch'], [0.0,-0.05], 0.15)\n"
            "print('OK')"
        )
        self._run_remote_python(self._build_qi_code(body), timeout=5.0)
        self._head_frozen = True

    def unfreeze_head(self):
        if not self._is_connected or not self._head_frozen:
            return
        body = (
            "motion=s.service('ALMotion')\n"
            "try:\n"
            "    aware=s.service('ALBasicAwareness')\n"
            "    aware.setEnabled(True)\n"
            "except Exception:\n"
            "    pass\n"
            "motion.setStiffnesses('Head', 0.6)\n"
            "print('OK')"
        )
        self._run_remote_python(self._build_qi_code(body), timeout=5.0)
        self._head_frozen = False

    # UTILITAIRES

    def get_status(self) -> dict:
        return {
            "type": "ssh_bridge",
            "ip": self.ip,
            "ssh_user": self.ssh_user,
            "ssh_port": self.ssh_port,
            "is_connected": self._is_connected,
            "is_capturing_audio": self._is_capturing,
            "is_streaming_video": self._is_streaming_video,
            "stats": {
                "audio_frames_sent": self._audio_frames_sent,
                "audio_frames_received": self._audio_frames_received,
                "video_frames_sent": self._video_frames_sent,
            },
        }
