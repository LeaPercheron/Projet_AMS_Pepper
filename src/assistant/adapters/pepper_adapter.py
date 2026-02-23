# Adaptateur Robot Pepper

import socket
import struct
import threading
import time
import io
import wave
import audioop
import os
import base64
from typing import Optional, Callable, List
from .base import RobotAdapter, AdapterConfig, LEDColor


class PepperAdapter(RobotAdapter):
    # Adaptateur pour robot Pepper reel.

    def __init__(
        # Initialise l'objet.
        self,
        ip: str,
        port: int = 9559,
        config: Optional[AdapterConfig] = None
    ):
        super().__init__(config)
        self.ip = ip
        self.port = port

        # NAOqi session et services
        self._session = None
        self._audio_service = None
        self._tts_service = None
        self._led_service = None
        self._video_service = None
        self._memory_service = None
        self._tablet_service = None
        self._motion_service = None
        self._awareness_service = None
        self._audio_recorder_service = None
        self._file_manager_service = None
        self._python_bridge_service = None

        # Sockets audio
        self._audio_capture_socket: Optional[socket.socket] = None
        self._audio_playback_socket: Optional[socket.socket] = None

        # Threads
        self._capture_thread: Optional[threading.Thread] = None
        self._playback_thread: Optional[threading.Thread] = None
        self._video_thread: Optional[threading.Thread] = None

        # Etat
        self._is_capturing = False
        self._is_playing = False
        self._is_streaming_video = False
        self._audio_pull_mode = False
        self._audio_pull_detected_channels: Optional[int] = None
        self._audio_pull_detected_rate: Optional[int] = None
        self._audio_pull_empty_streak = 0
        self._audio_pull_chunk_count = 0
        self._audio_callback: Optional[Callable] = None
        self._video_callback: Optional[Callable] = None
        self._head_frozen = False
        self._awareness_was_enabled: Optional[bool] = None
        self._camera_ids = self._parse_camera_ids(os.getenv("PEPPER_CAMERA_IDS", "0"))
        self._camera_capture_index = 0
        self._camera_debug = (
            self._env_flag("PEPPER_CAMERA_DEBUG")
            or self._env_flag("PEPPER_BARCODE_DEBUG")
        )
        self._camera_resolution = max(0, int(os.getenv("PEPPER_CAMERA_RESOLUTION", "2") or 2))

    @staticmethod
    def _env_flag(name: str, default: bool = False) -> bool:
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _parse_camera_ids(raw: str) -> List[int]:
        ids: List[int] = []
        for token in str(raw or "").replace(";", ",").split(","):
            token = token.strip()
            if not token:
                continue
            try:
                cam_id = int(token)
            except Exception:
                continue
            if cam_id < 0 or cam_id > 3:
                continue
            if cam_id not in ids:
                ids.append(cam_id)
        return ids or [0]

    def _iter_camera_ids_for_capture(self) -> List[int]:
        if not self._camera_ids:
            self._camera_ids = [0]
        if len(self._camera_ids) == 1:
            return [self._camera_ids[0]]
        start = self._camera_capture_index % len(self._camera_ids)
        ordered = self._camera_ids[start:] + self._camera_ids[:start]
        self._camera_capture_index = (self._camera_capture_index + 1) % len(self._camera_ids)
        return ordered

    # CONNEXION

    def connect(self) -> bool:
        # Etablit la connexion avec Pepper.
        try:
            import qi
        except ImportError:
            print("[Pepper] SDK NAOqi (qi) non disponible")
            return False

        try:
            print(f"[Pepper] Connexion a {self.ip}:{self.port}...")

            self._session = qi.Session()
            self._session.connect(f"tcp://{self.ip}:{self.port}")

            # Recuperer les services
            self._audio_service = self._session.service("ALAudioDevice")
            self._tts_service = self._session.service("ALTextToSpeech")
            self._led_service = self._session.service("ALLeds")
            self._video_service = self._session.service("ALVideoDevice")
            self._memory_service = self._session.service("ALMemory")

            try:
                self._tablet_service = self._session.service("ALTabletService")
            except:
                print("[Pepper] Service tablette non disponible")

            try:
                self._motion_service = self._session.service("ALMotion")
            except:
                print("[Pepper] Service motion non disponible")

            try:
                self._awareness_service = self._session.service("ALBasicAwareness")
            except:
                self._awareness_service = None

            try:
                self._audio_recorder_service = self._session.service("ALAudioRecorder")
            except:
                print("[Pepper] Service audio recorder non disponible")

            try:
                self._file_manager_service = self._session.service("ALFileManager")
            except:
                print("[Pepper] Service file manager non disponible")
            try:
                self._python_bridge_service = self._session.service("ALPythonBridge")
            except:
                self._python_bridge_service = None
                if os.getenv("PEPPER_AUDIO_DEBUG", "0").strip().lower() in {"1", "true", "yes", "on"}:
                    print("[Pepper] Service ALPythonBridge non disponible")

            self._is_connected = True
            print("[Pepper] Connecte avec succes")
            return True

        except Exception as e:
            print(f"[Pepper] Erreur connexion: {e}")
            self._is_connected = False
            return False

    def disconnect(self):
        # Ferme la connexion avec Pepper.
        self.unfreeze_head()
        self.stop_audio_capture()
        self.stop_audio_playback()
        self.stop_video_stream()

        if self._session:
            try:
                self._session.close()
            except:
                pass
            self._session = None

        self._is_connected = False
        print("[Pepper] Deconnecte")

    # AUDIO

    def start_audio_capture(self, callback: Callable[[bytes], None]) -> bool:
        # Demarre la capture audio depuis les microphones Pepper.
        if not self._is_connected or not self._audio_service:
            return False

        if self._is_capturing:
            return True

        self._audio_callback = callback
        self._is_capturing = True
        self._audio_pull_mode = False
        self._audio_pull_detected_channels = None
        self._audio_pull_detected_rate = None
        self._audio_pull_empty_streak = 0
        self._audio_pull_chunk_count = 0

        # Mode 1 (historique): flux custom via ALAudioDevice + socket.
        try:
            self._audio_service.setClientPreferences(
                "PepperAssistant",
                self.config.sample_rate,
                self.config.channels_in,
                0  # Interleaved
            )
            self._audio_service.subscribe("PepperAssistant")
            self._capture_thread = threading.Thread(
                target=self._audio_capture_loop,
                daemon=True
            )
            self._capture_thread.start()
            print("[Pepper] Capture audio demarree")
            return True
        except Exception as e:
            print(f"[Pepper] Erreur config audio: {e}")
            # Mode 2 (fallback): chunks WAV via ALAudioRecorder.
            if not self._audio_recorder_service:
                self._is_capturing = False
                return False
            self._audio_pull_mode = True
            self._capture_thread = threading.Thread(
                target=self._audio_capture_pull_loop,
                daemon=True
            )
            self._capture_thread.start()
            print("[Pepper] Capture audio fallback ALAudioRecorder demarree")
            return True

    def _audio_capture_pull_loop(self):
        # Fallback: enregistre de petits WAV puis renvoie PCM brut au callback.
        while self._is_capturing:
            try:
                wav_bytes = self._pull_audio_chunk_wav(duration_s=0.6)
                if not wav_bytes:
                    self._audio_pull_empty_streak += 1
                    if self._audio_pull_empty_streak % 8 == 0:
                        print("[Pepper] Avertissement: aucun chunk audio récupéré (fallback recorder).")
                    time.sleep(0.2)
                    continue
                self._audio_pull_empty_streak = 0
                pcm_bytes = self._wav_to_pcm(wav_bytes)
                if pcm_bytes and self._audio_callback:
                    self._audio_pull_chunk_count += 1
                    if os.getenv("PEPPER_AUDIO_DEBUG", "0").strip().lower() in {"1", "true", "yes", "on"}:
                        if self._audio_pull_chunk_count % 8 == 0:
                            try:
                                rms = int(audioop.rms(pcm_bytes, 2))
                            except Exception:
                                rms = -1
                            print(
                                "[Pepper] Audio fallback chunk "
                                f"#{self._audio_pull_chunk_count} "
                                f"(rate={self._audio_pull_detected_rate}, "
                                f"ch={self._audio_pull_detected_channels}, rms={rms})"
                            )
                    self._audio_callback(pcm_bytes)
            except Exception as e:
                if self._is_capturing:
                    print(f"[Pepper] Erreur capture fallback: {e}")
                time.sleep(0.3)

    def _pull_audio_chunk_wav(self, duration_s: float = 0.6) -> bytes:
        if not self._audio_recorder_service:
            return b""

        explicit_path = os.getenv("PEPPER_AUDIO_RECORDER_PATH", "").strip()
        candidate_paths = []
        if explicit_path:
            candidate_paths.append(explicit_path)
        candidate_paths.extend([
            "/home/nao/recordings/pepper_capture_chunk.wav",
            "/home/nao/pepper_capture_chunk.wav",
            "/tmp/pepper_capture_chunk.wav",
            "pepper_capture_chunk.wav",
        ])
        # Uniques, ordre conservé.
        seen = set()
        paths = []
        for p in candidate_paths:
            if p and p not in seen:
                seen.add(p)
                paths.append(p)

        front_only = os.getenv("PEPPER_AUDIO_RECORDER_FRONT_ONLY", "1").strip().lower() in {"1", "true", "yes", "on"}
        if front_only:
            # Ordre NAOqi: [Left, Right, Front, Rear].
            channels = [0, 0, 1, 0]
            sample_rate = 16000
        else:
            channels = [1, 1, 1, 1]
            sample_rate = int(self.config.sample_rate or 48000)

        for robot_path in paths:
            try:
                # Si une capture précédente est restée ouverte côté robot.
                try:
                    self._audio_recorder_service.stopMicrophonesRecording()
                except Exception:
                    pass
                self._audio_recorder_service.startMicrophonesRecording(
                    robot_path,
                    "wav",
                    sample_rate,
                    channels
                )
                time.sleep(max(0.2, duration_s))
                self._audio_recorder_service.stopMicrophonesRecording()
            except Exception as e:
                if os.getenv("PEPPER_AUDIO_DEBUG", "0").strip().lower() in {"1", "true", "yes", "on"}:
                    print(f"[Pepper] Erreur start/stop recorder ({robot_path}): {e}")
                try:
                    self._audio_recorder_service.stopMicrophonesRecording()
                except Exception:
                    pass
                continue

            # Laisser un délai et retenter quelques fois pour le flush fichier côté robot.
            for _ in range(8):
                data = self._read_file_via_python_bridge(robot_path)
                if data:
                    return data
                data = self._read_file_via_file_manager(robot_path)
                if data:
                    return data
                time.sleep(0.08)

            if os.getenv("PEPPER_AUDIO_DEBUG", "0").strip().lower() in {"1", "true", "yes", "on"}:
                print(f"[Pepper] WAV introuvable après enregistrement: {robot_path}")

        if os.getenv("PEPPER_AUDIO_DEBUG", "0").strip().lower() in {"1", "true", "yes", "on"}:
            print("[Pepper] Impossible de lire le WAV capturé depuis le robot (tous chemins testés).")
        return b""

    def _read_file_via_file_manager(self, robot_path: str) -> bytes:
        if not self._file_manager_service:
            return b""

        read_paths = [robot_path]
        base = os.path.basename(robot_path)
        if base and base not in read_paths:
            read_paths.append(base)
        if robot_path.startswith("/home/nao/"):
            rel = robot_path[len("/home/nao/"):]
            if rel and rel not in read_paths:
                read_paths.append(rel)

        for path in read_paths:
            for method_name in ("getFile", "getFileContents", "readFile", "read"):
                if not hasattr(self._file_manager_service, method_name):
                    continue
                try:
                    payload = getattr(self._file_manager_service, method_name)(path)
                    data = self._normalize_file_payload(payload)
                    if data:
                        return data
                except Exception as e:
                    # Trop verbeux en runtime: on log uniquement les erreurs "autres"
                    # que "file does not exist", car ce cas est attendu pendant le flush.
                    if os.getenv("PEPPER_AUDIO_DEBUG", "0").strip().lower() in {"1", "true", "yes", "on"}:
                        msg = str(e)
                        if "does not exist" not in msg:
                            print(f"[Pepper] ALFileManager.{method_name} échec ({path}): {e}")
        return b""

    def _read_file_via_python_bridge(self, robot_path: str) -> bytes:
        if not self._python_bridge_service:
            return b""
        # ALPythonBridge.eval attend une expression.
        # Cette forme évite les scripts multi-lignes qui échouent silencieusement selon firmware.
        script = (
            "__import__('base64').b64encode("
            f"open({repr(robot_path)},'rb').read()"
            ")"
        )
        try:
            out = self._python_bridge_service.eval(script)
            if not out:
                return b""
            if isinstance(out, bytes):
                text = out.decode("ascii", errors="ignore")
            else:
                text = str(out)
            text = text.strip()
            if (text.startswith("b'") and text.endswith("'")) or (text.startswith('b"') and text.endswith('"')):
                text = text[2:-1]
            elif (text.startswith("u'") and text.endswith("'")) or (text.startswith('u"') and text.endswith('"')):
                text = text[2:-1]
            return base64.b64decode(text.encode("ascii", errors="ignore"))
        except Exception as e:
            if os.getenv("PEPPER_AUDIO_DEBUG", "0").strip().lower() in {"1", "true", "yes", "on"}:
                print(f"[Pepper] ALPythonBridge lecture WAV échec: {e}")
            return b""

    @staticmethod
    def _normalize_file_payload(payload) -> bytes:
        if payload is None:
            return b""
        if isinstance(payload, bytes):
            return payload
        if isinstance(payload, bytearray):
            return bytes(payload)
        if isinstance(payload, str):
            # Certains services renvoient directement le binaire encodé latin-1.
            return payload.encode("latin1", errors="ignore")
        if isinstance(payload, list):
            if len(payload) == 2:
                return PepperAdapter._normalize_file_payload(payload[1])
            try:
                return bytes(payload)
            except Exception:
                return b""
        if isinstance(payload, tuple):
            if len(payload) == 2:
                return PepperAdapter._normalize_file_payload(payload[1])
            try:
                return bytes(payload)
            except Exception:
                return b""
        return b""

    def _wav_to_pcm(self, wav_bytes: bytes) -> bytes:
        try:
            with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                self._audio_pull_detected_channels = int(wf.getnchannels() or 1)
                self._audio_pull_detected_rate = int(wf.getframerate() or self.config.sample_rate)
                sample_width = int(wf.getsampwidth() or 2)
                pcm = wf.readframes(wf.getnframes())
                if sample_width != 2:
                    pcm = audioop.lin2lin(pcm, sample_width, 2)
                return pcm
        except Exception:
            return b""

    def _audio_capture_loop(self):
        # Boucle de capture audio.
        try:
            # Creer socket serveur sur Mac
            self._audio_capture_socket = socket.socket(
                socket.AF_INET, socket.SOCK_STREAM
            )
            self._audio_capture_socket.setsockopt(
                socket.SOL_SOCKET, socket.SO_REUSEADDR, 1
            )
            self._audio_capture_socket.bind(('0.0.0.0', self.config.audio_capture_port))
            self._audio_capture_socket.listen(1)
            self._audio_capture_socket.settimeout(1.0)

            print(f"[Pepper] Attente connexion audio sur port {self.config.audio_capture_port}...")

            while self._is_capturing:
                try:
                    conn, addr = self._audio_capture_socket.accept()
                    print(f"[Pepper] Connexion audio de {addr}")

                    # Recevoir audio
                    while self._is_capturing:
                        # Header: taille (4 bytes)
                        header = conn.recv(12)
                        if len(header) < 12:
                            break

                        size, ts_sec, ts_usec = struct.unpack('<III', header)

                        # Donnees audio
                        data = b''
                        while len(data) < size:
                            chunk = conn.recv(min(4096, size - len(data)))
                            if not chunk:
                                break
                            data += chunk

                        if len(data) == size and self._audio_callback:
                            self._audio_callback(data)

                    conn.close()

                except socket.timeout:
                    continue
                except Exception as e:
                    if self._is_capturing:
                        print(f"[Pepper] Erreur capture: {e}")
                    break

        finally:
            if self._audio_capture_socket:
                self._audio_capture_socket.close()

    def stop_audio_capture(self):
        # Arrete la capture audio.
        self._is_capturing = False

        if self._audio_service and not self._audio_pull_mode:
            try:
                self._audio_service.unsubscribe("PepperAssistant")
            except:
                pass
        if self._audio_pull_mode and self._audio_recorder_service:
            try:
                self._audio_recorder_service.stopMicrophonesRecording()
            except Exception:
                pass

        if self._capture_thread:
            self._capture_thread.join(timeout=2.0)
            self._capture_thread = None

        if self._audio_capture_socket:
            self._audio_capture_socket.close()
            self._audio_capture_socket = None

        self._audio_pull_mode = False
        print("[Pepper] Capture audio arretee")

    def play_audio(self, audio_bytes: bytes) -> bool:
        # Joue de l'audio sur les haut-parleurs Pepper.
        if not self._is_connected:
            return False

        # Envoyer via socket au robot
        try:
            if not self._audio_playback_socket:
                self._audio_playback_socket = socket.socket(
                    socket.AF_INET, socket.SOCK_STREAM
                )
                self._audio_playback_socket.connect(
                    (self.ip, self.config.audio_playback_port)
                )

            # Header + data
            header = struct.pack('<I', len(audio_bytes))
            self._audio_playback_socket.sendall(header + audio_bytes)
            return True

        except Exception as e:
            print(f"[Pepper] Erreur playback: {e}")
            self._audio_playback_socket = None
            return self._play_audio_naoqi(audio_bytes)

    def _play_audio_naoqi(self, audio_bytes: bytes) -> bool:
        # Fallback playback direct via ALAudioDevice.
        if not self._audio_service or not audio_bytes:
            return False
        attempts = [
            (audio_bytes, self.config.channels_out, self.config.sample_rate),
            (self.config.channels_out, self.config.sample_rate, audio_bytes),
            (self.config.sample_rate, self.config.channels_out, audio_bytes),
            (self.config.sample_rate, audio_bytes, self.config.channels_out),
        ]
        for args in attempts:
            try:
                self._audio_service.sendRemoteBufferToOutput(*args)
                return True
            except Exception:
                continue
        return False

    def stop_audio_playback(self):
        # Arrete la lecture audio.
        if self._audio_playback_socket:
            try:
                self._audio_playback_socket.close()
            except:
                pass
            self._audio_playback_socket = None

    # LEDs

    def set_led_color(self, color: LEDColor, fade: bool = True):
        # Change la couleur des LEDs.
        r, g, b = color.value
        self.set_led_rgb(r, g, b, fade)

    def set_led_rgb(self, r: int, g: int, b: int, fade: bool = True):
        # Change la couleur des LEDs avec valeurs RGB.
        if not self._is_connected or not self._led_service:
            return

        try:
            # Convertir RGB 0-255 en 0x00RRGGBB
            color_int = (r << 16) | (g << 8) | b

            if fade:
                self._led_service.fadeRGB(
                    "FaceLeds",
                    color_int,
                    self.config.led_fade_duration
                )
            else:
                self._led_service.setIntensity("FaceLeds", 1.0)
                self._led_service.fadeRGB("FaceLeds", color_int, 0.0)

        except Exception as e:
            print(f"[Pepper] Erreur LED: {e}")

    # CAMERA

    def capture_image(self) -> Optional[bytes]:
        # Capture une image depuis la camera.
        if not self._is_connected or not self._video_service:
            return None

        frames = self.capture_images(num_frames=1, interval_s=0.0)
        if frames:
            return frames[0]
        if self._camera_debug:
            print("[Pepper] Capture image: aucune frame reçue sur les caméras configurées.")
        return None

    def capture_images(
        self,
        num_frames: int = 3,
        interval_s: float = 0.12,
        resolution: Optional[int] = None,
    ) -> List[bytes]:
        # Capture un burst d'images en gardant un abonnement caméra unique.
        if not self._is_connected or not self._video_service:
            return []

        target_frames = max(1, int(num_frames))
        delay_s = max(0.0, float(interval_s))

        for camera_id in self._iter_camera_ids_for_capture():
            started = time.time()
            burst = self._capture_images_from_camera(
                camera_id=int(camera_id),
                num_frames=target_frames,
                interval_s=delay_s,
                resolution=resolution,
            )
            if burst:
                if self._camera_debug:
                    elapsed = time.time() - started
                    print(
                        f"[Pepper] Camera {camera_id}: burst {len(burst)}/{target_frames} "
                        f"frame(s) en {elapsed:.2f}s."
                    )
                return burst
        return []

    def _capture_image_from_camera(self, camera_id: int) -> Optional[bytes]:
        burst = self._capture_images_from_camera(
            camera_id=int(camera_id),
            num_frames=1,
            interval_s=0.0,
            resolution=None,
        )
        return burst[0] if burst else None

    def _capture_images_from_camera(
        self,
        camera_id: int,
        num_frames: int,
        interval_s: float,
        resolution: Optional[int] = None,
    ) -> List[bytes]:
        if not self._video_service:
            return []

        capture_resolution = self._camera_resolution if resolution is None else int(resolution)
        colorspace = 11  # RGB
        fps = max(1, int(os.getenv("PEPPER_CAMERA_FPS", "5") or 5))
        video_client = None
        captured: List[bytes] = []

        try:
            video_client = self._video_service.subscribeCamera(
                f"PepperAssistantCam{camera_id}_{int(time.time() * 1000) % 100000}",
                int(camera_id),
                capture_resolution,
                colorspace,
                fps
            )

            for idx in range(max(1, int(num_frames))):
                image = self._video_service.getImageRemote(video_client)
                if not image or len(image) < 7:
                    if self._camera_debug:
                        print(f"[Pepper] Camera {camera_id}: aucune image reçue (frame {idx + 1}).")
                    if idx < num_frames - 1 and interval_s > 0:
                        time.sleep(interval_s)
                    continue

                width = int(image[0]) if len(image) > 0 else 0
                height = int(image[1]) if len(image) > 1 else 0
                raw = image[6]
                payload = bytes(raw) if isinstance(raw, (bytes, bytearray)) else bytes(bytearray(raw))

                if payload:
                    captured.append(payload)
                    if self._camera_debug:
                        print(
                            f"[Pepper] Camera {camera_id}: frame {idx + 1}/{num_frames} "
                            f"{width}x{height}, {len(payload)} octets."
                        )

                if idx < num_frames - 1 and interval_s > 0:
                    time.sleep(interval_s)

        except Exception as e:
            if self._camera_debug:
                print(f"[Pepper] Erreur capture camera {camera_id}: {e}")
            return captured
        finally:
            if video_client:
                try:
                    self._video_service.unsubscribe(video_client)
                except Exception:
                    pass
        return captured

    def start_video_stream(self, callback: Callable[[bytes], None]) -> bool:
        # Demarre le flux video.
        if not self._is_connected or not self._video_service:
            return False

        self._video_callback = callback
        self._is_streaming_video = True

        self._video_thread = threading.Thread(
            target=self._video_stream_loop,
            daemon=True
        )
        self._video_thread.start()

        return True

    def _video_stream_loop(self):
        # Boucle de capture video.
        try:
            video_client = self._video_service.subscribeCamera(
                "PepperAssistantVideo",
                0, 2, 11, 10  # Front, VGA, RGB, 10fps
            )

            while self._is_streaming_video:
                image = self._video_service.getImageRemote(video_client)
                if image and self._video_callback:
                    self._video_callback(bytes(image[6]))
                time.sleep(0.1)

            self._video_service.unsubscribe(video_client)

        except Exception as e:
            print(f"[Pepper] Erreur stream video: {e}")

    def stop_video_stream(self):
        # Arrete le flux video.
        self._is_streaming_video = False
        if self._video_thread:
            self._video_thread.join(timeout=2.0)
            self._video_thread = None

    # PAROLE

    def say(self, text: str, blocking: bool = False) -> bool:
        # Fait parler Pepper.
        if not self._is_connected or not self._tts_service:
            return False

        try:
            if not blocking and hasattr(self._tts_service, "post"):
                self._tts_service.post.say(text)
            elif blocking:
                self._tts_service.say(text)
            else:
                # Certaines versions qi n'exposent pas .post.
                self._tts_service.say(text)
            return True
        except Exception as e:
            print(f"[Pepper] Erreur TTS: {e}")
            return False

    def stop_speaking(self):
        # Interrompt la parole.
        if self._tts_service:
            try:
                self._tts_service.stopAll()
            except:
                pass

    # DETECTION PRESENCE

    def is_person_present(self) -> bool:
        # Detecte si une personne est presente.
        if not self._is_connected or not self._memory_service:
            return False

        try:
            # Utiliser la detection de visage
            faces = self._memory_service.getData("FaceDetected")
            return faces is not None and len(faces) > 0
        except:
            return False

    def get_person_distance(self) -> Optional[float]:
        # Estime la distance de la personne.
        if not self._is_connected or not self._memory_service:
            return None

        try:
            # Utiliser le sonar
            distance = self._memory_service.getData(
                "Device/SubDeviceList/Platform/Front/Sonar/Sensor/Value"
            )
            return float(distance) if distance else None
        except:
            return None

    # TABLETTE

    def show_on_tablet(self, url: str) -> bool:
        # Affiche une URL sur la tablette.
        if not self._is_connected or not self._tablet_service:
            return False

        last_error = None
        for attempt in range(1, 4):
            try:
                # Après resetTablet, le service peut être présent mais pas prêt.
                if attempt > 1 and self._session:
                    try:
                        self._tablet_service = self._session.service("ALTabletService")
                    except Exception:
                        pass
                    time.sleep(1.0)

                # Séquence robuste: réveil + Wi-Fi + nettoyage WebView.
                try:
                    if hasattr(self._tablet_service, "wakeUp"):
                        self._tablet_service.wakeUp()
                except Exception:
                    pass

                try:
                    if hasattr(self._tablet_service, "setBrightness"):
                        self._tablet_service.setBrightness(1.0)
                except Exception:
                    pass

                try:
                    if hasattr(self._tablet_service, "enableWifi"):
                        self._tablet_service.enableWifi()
                except Exception:
                    pass

                try:
                    if hasattr(self._tablet_service, "hideWebview"):
                        self._tablet_service.hideWebview()
                except Exception:
                    pass

                try:
                    if hasattr(self._tablet_service, "cleanWebview"):
                        self._tablet_service.cleanWebview()
                except Exception:
                    pass

                result = self._tablet_service.showWebview(url)
                if result is False:
                    last_error = "showWebview returned False"
                    time.sleep(1.5)
                    continue

                try:
                    if hasattr(self._tablet_service, "reloadPage"):
                        # noCache=True si supporté, sinon appel simple.
                        try:
                            self._tablet_service.reloadPage(True)
                        except Exception:
                            self._tablet_service.reloadPage()
                except Exception:
                    pass

                return True
            except Exception as e:
                last_error = e
                time.sleep(1.5)

        if last_error is not None:
            print(f"[Pepper] Erreur tablette: {last_error}")
        return False

    def hide_tablet(self):
        # Cache le contenu de la tablette.
        if self._tablet_service:
            try:
                self._tablet_service.hideWebview()
            except:
                pass

    # MOUVEMENTS

    def wave(self):
        # Fait un geste de salut.
        if self._motion_service:
            try:
                # Animation de salut
                self._motion_service.post.angleInterpolation(
                    "RArm",
                    [[0.5, 1.0, 0.5]],  # Angles
                    [[0.5, 1.0, 1.5]],  # Temps
                    True
                )
            except:
                pass

    def nod(self):
        # Fait un hochement de tete.
        if self._motion_service:
            try:
                self._motion_service.post.angleInterpolation(
                    "HeadPitch",
                    [0.1, -0.1, 0.0],
                    [0.3, 0.6, 0.9],
                    True
                )
            except:
                pass

    def point_at_tablet(self):
        # Pointe vers la tablette.
        if self._motion_service:
            try:
                self._motion_service.post.setAngles(
                    "RArm",
                    [0.5, 0.0, 0.0, 0.5, 0.0, 0.0],
                    0.2
                )
            except:
                pass

    def freeze_head(self):
        # Bloque la tete pour éviter les mouvements pendant un scan.
        if self._head_frozen:
            return

        if self._awareness_service:
            try:
                enabled = self._awareness_service.isEnabled()
                self._awareness_was_enabled = bool(enabled)
            except Exception:
                self._awareness_was_enabled = None
            try:
                self._awareness_service.setEnabled(False)
            except Exception:
                pass

        if self._motion_service:
            try:
                self._motion_service.setStiffnesses("Head", 1.0)
                self._motion_service.setAngles(["HeadYaw", "HeadPitch"], [0.0, -0.05], 0.15)
            except Exception:
                pass

        self._head_frozen = True

    def unfreeze_head(self):
        # Restaure la tete après un scan.
        if not self._head_frozen:
            return

        if self._awareness_service and self._awareness_was_enabled:
            try:
                self._awareness_service.setEnabled(True)
            except Exception:
                pass

        if self._motion_service:
            try:
                self._motion_service.setStiffnesses("Head", 0.6)
            except Exception:
                pass

        self._awareness_was_enabled = None
        self._head_frozen = False

    # UTILITAIRES

    def get_status(self) -> dict:
        # Retourne l'etat du robot.
        return {
            "type": "pepper",
            "ip": self.ip,
            "port": self.port,
            "is_connected": self._is_connected,
            "is_capturing_audio": self._is_capturing,
            "is_streaming_video": self._is_streaming_video,
            "services": {
                "audio": self._audio_service is not None,
                "tts": self._tts_service is not None,
                "led": self._led_service is not None,
                "video": self._video_service is not None,
                "tablet": self._tablet_service is not None,
                "motion": self._motion_service is not None,
            }
        }
