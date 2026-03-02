# Adaptateur Mock (Simulation)

import threading
import time
import struct
import math
from typing import Optional, Callable
from .base import RobotAdapter, AdapterConfig, LEDColor


class MockAdapter(RobotAdapter):
    # Adaptateur de simulation pour tests sans robot.

    def __init__(self, config: Optional[AdapterConfig] = None):
        # Initialise l'objet.
        super().__init__(config)

        # Etat simulation
        self._is_capturing = False
        self._is_playing = False
        self._is_streaming_video = False
        self._audio_callback: Optional[Callable] = None
        self._video_callback: Optional[Callable] = None

        # Threads
        self._capture_thread: Optional[threading.Thread] = None
        self._video_thread: Optional[threading.Thread] = None

        # Etat simule
        self._current_led_color = LEDColor.OFF
        self._is_speaking = False
        self._person_present = True  # Par defaut, simule une personne
        self._person_distance = 1.5  # 1.5 metres

        # Compteurs
        self._audio_frames_sent = 0
        self._audio_frames_received = 0
        self._video_frames_sent = 0

    # CONNEXION

    def connect(self) -> bool:
        # Simule une connexion reussie.
        print("[Mock] Connexion simulee...")
        time.sleep(0.2)  # Simule delai
        self._is_connected = True
        print("[Mock] Connecte (simulation)")
        return True

    def disconnect(self):
        # Simule une deconnexion.
        self.stop_audio_capture()
        self.stop_audio_playback()
        self.stop_video_stream()
        self._is_connected = False
        print("[Mock] Deconnecte (simulation)")

    # AUDIO

    def start_audio_capture(self, callback: Callable[[bytes], None]) -> bool:
        # Demarre la capture audio simulee.
        if self._is_capturing:
            return True

        self._audio_callback = callback
        self._is_capturing = True

        self._capture_thread = threading.Thread(
            target=self._mock_audio_capture,
            daemon=True
        )
        self._capture_thread.start()

        print("[Mock] Capture audio demarree (simulation)")
        return True

    def _mock_audio_capture(self):
        # Genere un signal audio simule (sinusoide + bruit).
        sample_rate = self.config.sample_rate
        channels = self.config.channels_in
        buffer_size = 1024  # Samples par canal
        frequency = 440  # Hz (La)

        sample_count = 0

        while self._is_capturing:
            samples = []

            for i in range(buffer_size):
                t = (sample_count + i) / sample_rate

                # Signal simule: voix (sinusoide modulee) + bruit
                voice = 0.3 * math.sin(2 * math.pi * frequency * t)
                voice *= (1 + 0.3 * math.sin(2 * math.pi * 5 * t))  # Modulation

                # Ajouter un peu de bruit
                import random
                noise = 0.02 * (random.random() - 0.5)

                sample = int(32767 * (voice + noise))

                # Dupliquer sur 4 canaux (front plus fort)
                for ch in range(channels):
                    if ch == 0:  # Front
                        samples.append(sample)
                    elif ch == 1:  # Rear
                        samples.append(int(sample * 0.2))
                    else:  # Left/Right
                        samples.append(int(sample * 0.6))

            sample_count += buffer_size

            # Convertir en bytes PCM16
            audio_data = struct.pack(f'<{len(samples)}h', *samples)

            # Callback
            if self._audio_callback:
                self._audio_callback(audio_data)
                self._audio_frames_sent += 1

            # Attendre le temps reel du buffer
            time.sleep(buffer_size / sample_rate)

    def stop_audio_capture(self):
        # Arrete la capture audio simulee.
        self._is_capturing = False
        if self._capture_thread:
            self._capture_thread.join(timeout=2.0)
            self._capture_thread = None
        print("[Mock] Capture audio arretee")

    def play_audio(self, audio_bytes: bytes) -> bool:
        # Simule la lecture audio (affiche stats).
        if not self._is_connected:
            return False

        self._audio_frames_received += 1

        # En mode verbose, afficher
        if self._audio_frames_received % 50 == 0:
            print(f"[Mock] Audio recu: {len(audio_bytes)} bytes "
                  f"(frame {self._audio_frames_received})")

        return True

    def stop_audio_playback(self):
        # Arrete la lecture audio simulee.
        self._is_playing = False
        print(f"[Mock] Playback arrete ({self._audio_frames_received} frames recues)")

    # LEDs

    def set_led_color(self, color: LEDColor, fade: bool = True):
        # Simule un changement de couleur LED.
        old_color = self._current_led_color
        self._current_led_color = color

        fade_str = " (fade)" if fade else ""
        print(f"[Mock] LEDs: {old_color.name} -> {color.name}{fade_str}")

    def set_led_rgb(self, r: int, g: int, b: int, fade: bool = True):
        # Simule un changement de couleur LED RGB.
        fade_str = " (fade)" if fade else ""
        print(f"[Mock] LEDs: RGB({r}, {g}, {b}){fade_str}")

    # CAMERA

    def capture_image(self) -> Optional[bytes]:
        # Retourne une image de test (carré colore).
        # Generer une image RGB simple (10x10 pixels)
        width, height = 100, 100
        pixels = []

        for y in range(height):
            for x in range(width):
                # Gradient colore
                r = int(255 * x / width)
                g = int(255 * y / height)
                b = 128
                pixels.extend([r, g, b])

        return bytes(pixels)

    def start_video_stream(self, callback: Callable[[bytes], None]) -> bool:
        # Demarre un flux video simule.
        if self._is_streaming_video:
            return True

        self._video_callback = callback
        self._is_streaming_video = True

        self._video_thread = threading.Thread(
            target=self._mock_video_stream,
            daemon=True
        )
        self._video_thread.start()

        print("[Mock] Stream video demarre")
        return True

    def _mock_video_stream(self):
        # Genere des frames video simulees.
        while self._is_streaming_video:
            frame = self.capture_image()
            if frame and self._video_callback:
                self._video_callback(frame)
                self._video_frames_sent += 1
            time.sleep(0.1)  # 10 fps

    def stop_video_stream(self):
        # Arrete le flux video simule.
        self._is_streaming_video = False
        if self._video_thread:
            self._video_thread.join(timeout=2.0)
            self._video_thread = None
        print(f"[Mock] Stream video arrete ({self._video_frames_sent} frames)")

    # PAROLE

    def say(self, text: str, blocking: bool = False) -> bool:
        # Simule la parole (affiche en console).
        self._is_speaking = True
        print(f"[Mock] TTS: \"{text}\"")

        if blocking:
            # Simuler duree (~100ms par mot)
            words = len(text.split())
            time.sleep(words * 0.1)

        self._is_speaking = False
        return True

    def stop_speaking(self):
        # Interrompt la parole simulee.
        self._is_speaking = False
        print("[Mock] TTS interrompu")

    # DETECTION PRESENCE

    def is_person_present(self) -> bool:
        # Retourne l'etat de presence simule.
        return self._person_present

    def get_person_distance(self) -> Optional[float]:
        # Retourne la distance simulee.
        if self._person_present:
            return self._person_distance
        return None

    def set_person_present(self, present: bool, distance: float = 1.5):
        # Configure la simulation de presence.
        self._person_present = present
        self._person_distance = distance
        print(f"[Mock] Presence: {present}, distance: {distance}m")

    # TABLETTE

    def show_on_tablet(self, url: str) -> bool:
        # Simule l'affichage sur tablette.
        print(f"[Mock] Tablette: {url}")
        return True

    def hide_tablet(self):
        # Simule le masquage de la tablette.
        print("[Mock] Tablette masquee")

    # MOUVEMENTS

    def wave(self):
        # Simule un geste de salut.
        print("[Mock] Geste: salut")

    def nod(self):
        # Simule un hochement de tete.
        print("[Mock] Geste: hochement")

    def point_at_tablet(self):
        # Simule pointer vers tablette.
        print("[Mock] Geste: pointe tablette")

    # UTILITAIRES

    def get_status(self) -> dict:
        # Retourne l'etat de la simulation.
        return {
            "type": "mock",
            "is_connected": self._is_connected,
            "is_capturing_audio": self._is_capturing,
            "is_playing_audio": self._is_playing,
            "is_streaming_video": self._is_streaming_video,
            "is_speaking": self._is_speaking,
            "current_led": self._current_led_color.name,
            "person_present": self._person_present,
            "person_distance": self._person_distance,
            "stats": {
                "audio_frames_sent": self._audio_frames_sent,
                "audio_frames_received": self._audio_frames_received,
                "video_frames_sent": self._video_frames_sent,
            }
        }
