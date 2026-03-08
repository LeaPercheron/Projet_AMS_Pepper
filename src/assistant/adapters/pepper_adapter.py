# Adaptateur Robot Pepper

import socket
import struct
import threading
import time
import os
import ipaddress
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
from typing import Optional, Callable, List
from .base import RobotAdapter, AdapterConfig, LEDColor


class _ALAudioDeviceProxy:
    """
    Service enregistré dans la session qi locale pour recevoir
    les callbacks ALAudioDevice.processRemote() depuis Pepper.
    Évite entièrement le transfert de fichiers WAV et les sockets TCP.
    NAOqi appelle processRemote() via RPC qi pour chaque buffer audio.
    """

    def __init__(self, callback: Callable[[bytes], None], adapter: "PepperAdapter"):
        self._callback = callback
        self._adapter = adapter

    def processRemote(self, nbChannels: int, nbSamplesPerChan: int, timestamp, inputBuffer):
        try:
            pcm = bytes(bytearray(inputBuffer))
        except Exception:
            try:
                pcm = bytes(inputBuffer)
            except Exception:
                return
        if not pcm:
            return
        # Mettre à jour le format détecté (utilisé par voice_fallback).
        self._adapter._audio_pull_detected_channels = int(nbChannels or 1)
        if self._callback:
            self._callback(pcm)


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

        # Sockets audio
        self._audio_playback_socket: Optional[socket.socket] = None

        # Threads
        self._video_thread: Optional[threading.Thread] = None

        # Etat
        self._is_capturing = False
        self._is_playing = False
        self._is_streaming_video = False
        self._audio_pull_detected_channels: Optional[int] = None
        self._audio_pull_detected_rate: Optional[int] = None
        self._audio_callback: Optional[Callable] = None
        self._audio_proxy: Optional[_ALAudioDeviceProxy] = None
        self._audio_proxy_service_id: Optional[int] = None
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
        self._audio_pull_detected_channels = None
        self._audio_pull_detected_rate = None

        try:
            front_only = os.getenv("PEPPER_AUDIO_RECORDER_FRONT_ONLY", "1").strip().lower() in {
                "1", "true", "yes", "on"
            }
            rate = 16000 if front_only else int(self.config.sample_rate or 48000)
            proxy = _ALAudioDeviceProxy(callback, self)
            svc_id = self._session.registerService("PepperAssistantAudio", proxy)
            self._audio_proxy = proxy
            self._audio_proxy_service_id = svc_id
            self._audio_pull_detected_rate = rate
            self._audio_service.setClientPreferences("PepperAssistantAudio", rate, 4, 0)
            self._audio_service.subscribe("PepperAssistantAudio")
            print(f"[Pepper] Capture audio qi demarree ({rate} Hz, 4 canaux)")
            return True
        except Exception as e:
            print(f"[Pepper] Erreur capture audio qi: {e}")
            if self._audio_proxy_service_id is not None:
                try:
                    self._session.unregisterService(self._audio_proxy_service_id)
                except Exception:
                    pass
                self._audio_proxy_service_id = None
            self._audio_proxy = None
            self._is_capturing = False
            return False

    def stop_audio_capture(self):
        # Arrete la capture audio.
        self._is_capturing = False

        if self._audio_proxy_service_id is not None:
            if self._audio_service:
                try:
                    self._audio_service.unsubscribe("PepperAssistantAudio")
                except Exception:
                    pass
            if self._session:
                try:
                    self._session.unregisterService(self._audio_proxy_service_id)
                except Exception:
                    pass
            self._audio_proxy_service_id = None
        self._audio_proxy = None

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

    @staticmethod
    def _is_private_ip(host: str) -> bool:
        try:
            return ipaddress.ip_address(host).is_private
        except Exception:
            return False

    @staticmethod
    def _without_ws_query(url: str) -> str:
        # Retire seulement le paramètre ws=... de l'URL.
        try:
            parsed = urlparse(url or "")
            if not parsed.query:
                return url
            pairs = parse_qsl(parsed.query, keep_blank_values=True)
            filtered = [(k, v) for (k, v) in pairs if str(k).lower() != "ws"]
            new_query = urlencode(filtered, doseq=True)
            return urlunparse(parsed._replace(query=new_query))
        except Exception:
            return url

    def show_on_tablet(self, url: str) -> bool:
        # Affiche une URL sur la tablette.
        if not self._is_connected or not self._tablet_service:
            return False

        last_error = None
        parsed = urlparse(url or "")
        target_host = parsed.hostname or ""
        target_is_private_ip = self._is_private_ip(target_host)
        url_issue_hint = ""
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

                # Test rapide de santé WebView:
                # - si "about:blank" échoue, le souci vient de la tablette/service.
                # - si "about:blank" passe mais l'URL cible échoue, c'est souvent un souci réseau URL->Mac.
                blank_ok = None
                try:
                    blank_ok = bool(self._tablet_service.showWebview("about:blank"))
                except Exception:
                    blank_ok = None
                if blank_ok is False:
                    last_error = "tablet webview unavailable (about:blank returned False)"
                    # Tentative de reset tablette avant de réessayer.
                    try:
                        if hasattr(self._tablet_service, "resetTablet"):
                            self._tablet_service.resetTablet()
                            time.sleep(6.0)
                    except Exception:
                        pass
                    continue

                candidates = [url]
                sanitized = self._without_ws_query(url)
                if sanitized and sanitized != url:
                    candidates.append(sanitized)

                result = False
                used_url = url
                for candidate in candidates:
                    used_url = candidate
                    result = self._tablet_service.showWebview(candidate)
                    if result is not False:
                        break

                if result is False:
                    last_error = "showWebview returned False for target URL"
                    if blank_ok is True:
                        if target_is_private_ip:
                            url_issue_hint = (
                                f"URL cible inaccessible depuis Pepper: {target_host}. "
                                "Vérifie que Pepper et ton Mac sont sur le meme réseau IP."
                            )
                        else:
                            url_issue_hint = (
                                "URL cible inaccessible depuis Pepper (DNS/route/firewall)."
                            )
                    time.sleep(1.5)
                    continue
                elif used_url != url:
                    print(
                        "[Pepper] Tablette: URL avec paramètre ws refusée, "
                        "fallback sans ws utilisé."
                    )

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
                # Tentative de recovery service tablette en cas d'exception NAOqi.
                try:
                    if hasattr(self._tablet_service, "resetTablet"):
                        self._tablet_service.resetTablet()
                        time.sleep(6.0)
                except Exception:
                    pass
                time.sleep(1.5)

        if last_error is not None:
            print(f"[Pepper] Erreur tablette: {last_error}")
            if url_issue_hint:
                print(f"[Pepper] Diagnostic tablette: {url_issue_hint}")
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
