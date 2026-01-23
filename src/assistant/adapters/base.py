"""
Interface de Base pour Adaptateurs Robot
========================================
Definit le contrat que tout adaptateur doit implementer.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Callable, Any, Tuple
from enum import Enum


class LEDColor(Enum):
    """Couleurs predefinies pour les LEDs."""
    OFF = (0, 0, 0)
    WHITE = (255, 255, 255)
    RED = (255, 0, 0)
    GREEN = (0, 255, 0)
    BLUE = (0, 0, 255)
    YELLOW = (255, 255, 0)
    ORANGE = (255, 128, 0)
    PURPLE = (128, 0, 255)
    CYAN = (0, 255, 255)


@dataclass
class AdapterConfig:
    """Configuration de base pour les adaptateurs."""
    name: str = "robot"
    # Audio
    audio_capture_port: int = 5555
    audio_playback_port: int = 5556
    sample_rate: int = 48000
    channels_in: int = 4
    channels_out: int = 2
    # LEDs
    led_fade_duration: float = 0.3
    # Timeouts
    connection_timeout: float = 10.0
    command_timeout: float = 5.0


class RobotAdapter(ABC):
    """
    Interface abstraite pour controle du robot.

    Definit toutes les operations possibles sur le robot:
    - Audio (capture/playback)
    - LEDs
    - Camera
    - Parole synthetisee
    - Mouvement
    - Tablette
    """

    def __init__(self, config: Optional[AdapterConfig] = None):
        self.config = config or AdapterConfig()
        self._is_connected = False
        self._callbacks = {}

    @property
    def is_connected(self) -> bool:
        """Verifie si le robot est connecte."""
        return self._is_connected

    # =====================================================================
    # CONNEXION
    # =====================================================================

    @abstractmethod
    def connect(self) -> bool:
        """
        Etablit la connexion avec le robot.

        Returns:
            True si connexion reussie
        """
        pass

    @abstractmethod
    def disconnect(self):
        """Ferme la connexion avec le robot."""
        pass

    # =====================================================================
    # AUDIO
    # =====================================================================

    @abstractmethod
    def start_audio_capture(self, callback: Callable[[bytes], None]) -> bool:
        """
        Demarre la capture audio.

        Args:
            callback: Fonction appelee avec les donnees audio

        Returns:
            True si demarrage reussi
        """
        pass

    @abstractmethod
    def stop_audio_capture(self):
        """Arrete la capture audio."""
        pass

    @abstractmethod
    def play_audio(self, audio_bytes: bytes) -> bool:
        """
        Joue de l'audio sur les haut-parleurs.

        Args:
            audio_bytes: Audio PCM a jouer

        Returns:
            True si lecture demarree
        """
        pass

    @abstractmethod
    def stop_audio_playback(self):
        """Arrete la lecture audio."""
        pass

    # =====================================================================
    # LEDs
    # =====================================================================

    @abstractmethod
    def set_led_color(self, color: LEDColor, fade: bool = True):
        """
        Change la couleur des LEDs des yeux.

        Args:
            color: Couleur a appliquer
            fade: Si True, transition douce
        """
        pass

    @abstractmethod
    def set_led_rgb(self, r: int, g: int, b: int, fade: bool = True):
        """
        Change la couleur des LEDs avec valeurs RGB.

        Args:
            r, g, b: Valeurs 0-255
            fade: Si True, transition douce
        """
        pass

    # =====================================================================
    # CAMERA
    # =====================================================================

    @abstractmethod
    def capture_image(self) -> Optional[bytes]:
        """
        Capture une image depuis la camera.

        Returns:
            Image en bytes (JPEG) ou None si erreur
        """
        pass

    @abstractmethod
    def start_video_stream(self, callback: Callable[[bytes], None]) -> bool:
        """
        Demarre le flux video.

        Args:
            callback: Fonction appelee avec chaque frame

        Returns:
            True si demarrage reussi
        """
        pass

    @abstractmethod
    def stop_video_stream(self):
        """Arrete le flux video."""
        pass

    # =====================================================================
    # PAROLE
    # =====================================================================

    @abstractmethod
    def say(self, text: str, blocking: bool = False) -> bool:
        """
        Fait parler le robot avec TTS integre.

        Args:
            text: Texte a prononcer
            blocking: Si True, attend la fin

        Returns:
            True si parole demarree
        """
        pass

    @abstractmethod
    def stop_speaking(self):
        """Interrompt la parole en cours."""
        pass

    # =====================================================================
    # DETECTION PRESENCE
    # =====================================================================

    @abstractmethod
    def is_person_present(self) -> bool:
        """
        Detecte si une personne est devant le robot.

        Returns:
            True si personne detectee
        """
        pass

    @abstractmethod
    def get_person_distance(self) -> Optional[float]:
        """
        Estime la distance de la personne.

        Returns:
            Distance en metres ou None si pas de personne
        """
        pass

    # =====================================================================
    # TABLETTE
    # =====================================================================

    @abstractmethod
    def show_on_tablet(self, url: str) -> bool:
        """
        Affiche une URL sur la tablette.

        Args:
            url: URL a afficher

        Returns:
            True si affichage reussi
        """
        pass

    @abstractmethod
    def hide_tablet(self):
        """Cache le contenu de la tablette."""
        pass

    # =====================================================================
    # MOUVEMENTS (optionnel)
    # =====================================================================

    def wave(self):
        """Fait un geste de salut."""
        pass

    def nod(self):
        """Fait un hochement de tete."""
        pass

    def point_at_tablet(self):
        """Pointe vers la tablette."""
        pass

    # =====================================================================
    # UTILITAIRES
    # =====================================================================

    def register_callback(self, event: str, callback: Callable):
        """Enregistre un callback pour un evenement."""
        if event not in self._callbacks:
            self._callbacks[event] = []
        self._callbacks[event].append(callback)

    def _emit(self, event: str, *args, **kwargs):
        """Emet un evenement vers les callbacks."""
        for callback in self._callbacks.get(event, []):
            try:
                callback(*args, **kwargs)
            except Exception as e:
                print(f"[Adapter] Erreur callback {event}: {e}")

    @abstractmethod
    def get_status(self) -> dict:
        """
        Retourne l'etat du robot.

        Returns:
            Dictionnaire avec infos de statut
        """
        pass
