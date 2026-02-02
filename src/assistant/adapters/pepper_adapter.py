# Adaptateur Robot Pepper

import socket
import struct
import threading
import time
from typing import Optional, Callable
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
        self._audio_callback: Optional[Callable] = None
        self._video_callback: Optional[Callable] = None

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

            self._is_connected = True
            print("[Pepper] Connecte avec succes")
            return True

        except Exception as e:
            print(f"[Pepper] Erreur connexion: {e}")
            self._is_connected = False
            return False

    def disconnect(self):
        # Ferme la connexion avec Pepper.
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

        # Configurer capture
        try:
            self._audio_service.setClientPreferences(
                "PepperAssistant",
                self.config.sample_rate,
                self.config.channels_in,
                0  # Interleaved
            )
            self._audio_service.subscribe("PepperAssistant")
        except Exception as e:
            print(f"[Pepper] Erreur config audio: {e}")

        # Thread de capture via socket
        self._capture_thread = threading.Thread(
            target=self._audio_capture_loop,
            daemon=True
        )
        self._capture_thread.start()

        print("[Pepper] Capture audio demarree")
        return True

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

        if self._audio_service:
            try:
                self._audio_service.unsubscribe("PepperAssistant")
            except:
                pass

        if self._capture_thread:
            self._capture_thread.join(timeout=2.0)
            self._capture_thread = None

        if self._audio_capture_socket:
            self._audio_capture_socket.close()
            self._audio_capture_socket = None

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

        try:
            # S'abonner a la camera
            resolution = 2  # VGA (640x480)
            colorspace = 11  # RGB
            fps = 5

            video_client = self._video_service.subscribeCamera(
                "PepperAssistant",
                0,  # Camera frontale
                resolution,
                colorspace,
                fps
            )

            # Capturer une frame
            image = self._video_service.getImageRemote(video_client)

            # Desabonner
            self._video_service.unsubscribe(video_client)

            if image:
                # image[6] contient les donnees brutes
                return bytes(image[6])

            return None

        except Exception as e:
            print(f"[Pepper] Erreur capture image: {e}")
            return None

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
            if blocking:
                self._tts_service.say(text)
            else:
                self._tts_service.post.say(text)
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

        try:
            self._tablet_service.showWebview(url)
            return True
        except Exception as e:
            print(f"[Pepper] Erreur tablette: {e}")
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
