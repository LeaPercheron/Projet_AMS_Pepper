#!/usr/bin/env python3
"""
Phase 3 - Module OpenAI Realtime API
====================================
Communication bidirectionnelle WebSocket avec OpenAI Realtime API.
Gère l'envoi/réception audio en streaming pour conversation vocale.

Architecture:
    Pepper Mic → Mac → [Ce module] → OpenAI Realtime → [Ce module] → Mac → Pepper Speaker

API Reference: https://platform.openai.com/docs/guides/realtime

Usage:
    from openai_realtime import OpenAIRealtimeClient

    client = OpenAIRealtimeClient(api_key="sk-...")
    client.connect()
    client.send_audio(audio_bytes)
    # Les réponses arrivent via callbacks
"""

import asyncio
import base64
import json
import time
import struct
import threading
import os
from typing import Optional, Callable, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum
from collections import deque
import logging

# Configuration logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

# OpenAI Realtime API
OPENAI_REALTIME_URL = "wss://api.openai.com/v1/realtime"
OPENAI_REALTIME_MODEL = "gpt-4o-realtime-preview-2024-10-01"

# Format audio OpenAI Realtime
OPENAI_SAMPLE_RATE = 24000      # Hz
OPENAI_CHANNELS = 1              # Mono
OPENAI_SAMPLE_WIDTH = 2          # 16-bit PCM

# Chunks d'envoi
CHUNK_DURATION_MS = 100          # 100ms par chunk
CHUNK_SAMPLES = int(OPENAI_SAMPLE_RATE * CHUNK_DURATION_MS / 1000)  # 2400 samples
CHUNK_BYTES = CHUNK_SAMPLES * OPENAI_SAMPLE_WIDTH  # 4800 bytes

# Format audio Pepper (sortie)
PEPPER_SAMPLE_RATE = 48000
PEPPER_CHANNELS = 2              # Stéréo


class ConnectionState(Enum):
    """États de connexion WebSocket."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"


class ConversationState(Enum):
    """États de la conversation."""
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"


@dataclass
class RealtimeConfig:
    """Configuration du client Realtime."""
    api_key: str = ""
    model: str = OPENAI_REALTIME_MODEL

    # Voice
    voice: str = "alloy"  # alloy, echo, fable, onyx, nova, shimmer

    # Audio
    input_audio_format: str = "pcm16"
    output_audio_format: str = "pcm16"

    # Turn detection (VAD)
    turn_detection_type: str = "server_vad"  # server_vad ou none
    turn_detection_threshold: float = 0.5
    turn_detection_prefix_padding_ms: int = 300
    turn_detection_silence_duration_ms: int = 500

    # Modalities
    modalities: List[str] = field(default_factory=lambda: ["text", "audio"])

    # Instructions système (prompt)
    instructions: str = ""

    # Reconnexion
    auto_reconnect: bool = True
    max_reconnect_attempts: int = 5
    reconnect_delay_ms: int = 1000


@dataclass
class LatencyMetrics:
    """Métriques de latence."""
    speech_end_time: float = 0.0
    first_audio_time: float = 0.0
    time_to_first_byte_ms: float = 0.0
    total_response_time_ms: float = 0.0

    # Historique
    ttfb_history: List[float] = field(default_factory=list)

    def record_speech_end(self):
        """Enregistre la fin de parole utilisateur."""
        self.speech_end_time = time.time()

    def record_first_audio(self):
        """Enregistre la réception du premier byte audio."""
        self.first_audio_time = time.time()
        if self.speech_end_time > 0:
            self.time_to_first_byte_ms = (self.first_audio_time - self.speech_end_time) * 1000
            self.ttfb_history.append(self.time_to_first_byte_ms)
            # Garder les 100 derniers
            if len(self.ttfb_history) > 100:
                self.ttfb_history.pop(0)

    def get_avg_ttfb(self) -> float:
        """Retourne la latence moyenne TTFB."""
        if not self.ttfb_history:
            return 0.0
        return sum(self.ttfb_history) / len(self.ttfb_history)


# =============================================================================
# CONVERTISSEUR AUDIO
# =============================================================================

class AudioConverter:
    """Conversion audio entre formats Pepper et OpenAI."""

    @staticmethod
    def resample_48k_to_24k(audio_48k: bytes) -> bytes:
        """
        Resample 48kHz → 24kHz (division par 2).
        Utilise une moyenne de 2 samples consécutifs.
        """
        import numpy as np

        # Décoder PCM16
        samples = np.frombuffer(audio_48k, dtype=np.int16).astype(np.float32)

        # Resample par 2 (moyenne)
        # Pad si nombre impair
        if len(samples) % 2 != 0:
            samples = np.append(samples, samples[-1])

        resampled = (samples[::2] + samples[1::2]) / 2

        # Encoder PCM16
        return resampled.astype(np.int16).tobytes()

    @staticmethod
    def resample_24k_to_48k(audio_24k: bytes) -> bytes:
        """
        Resample 24kHz → 48kHz (multiplication par 2).
        Interpolation linéaire.
        """
        import numpy as np

        # Décoder PCM16
        samples = np.frombuffer(audio_24k, dtype=np.int16).astype(np.float32)

        # Interpolation linéaire (doubler avec interpolation)
        resampled = np.zeros(len(samples) * 2, dtype=np.float32)
        resampled[::2] = samples
        resampled[1::2] = (samples + np.roll(samples, -1)) / 2
        resampled[-1] = samples[-1]  # Dernier sample

        # Encoder PCM16
        return resampled.astype(np.int16).tobytes()

    @staticmethod
    def mono_to_stereo(audio_mono: bytes) -> bytes:
        """
        Convertit mono → stéréo (duplication).
        """
        import numpy as np

        # Décoder PCM16 mono
        samples = np.frombuffer(audio_mono, dtype=np.int16)

        # Dupliquer pour stéréo (interleaved: L,R,L,R,...)
        stereo = np.empty(len(samples) * 2, dtype=np.int16)
        stereo[::2] = samples   # Canal gauche
        stereo[1::2] = samples  # Canal droit

        return stereo.tobytes()

    @staticmethod
    def convert_for_pepper(audio_24k_mono: bytes) -> bytes:
        """
        Convertit l'audio OpenAI pour Pepper.
        24kHz mono → 48kHz stéréo
        """
        audio_48k = AudioConverter.resample_24k_to_48k(audio_24k_mono)
        audio_stereo = AudioConverter.mono_to_stereo(audio_48k)
        return audio_stereo

    @staticmethod
    def convert_for_openai(audio_48k_mono: bytes) -> bytes:
        """
        Convertit l'audio traité (déjà mono) pour OpenAI.
        48kHz mono → 24kHz mono (fait par Phase 2)
        """
        return AudioConverter.resample_48k_to_24k(audio_48k_mono)


# =============================================================================
# CLIENT OPENAI REALTIME
# =============================================================================

class OpenAIRealtimeClient:
    """
    Client WebSocket pour OpenAI Realtime API.

    Gère:
    - Connexion/reconnexion WebSocket
    - Envoi audio en streaming (base64)
    - Réception audio en streaming
    - Callbacks pour événements
    """

    def __init__(self, config: Optional[RealtimeConfig] = None):
        self.config = config or RealtimeConfig()

        # Charger API key depuis env si non fournie
        if not self.config.api_key:
            self.config.api_key = os.getenv("OPENAI_API_KEY", "")

        # État
        self.connection_state = ConnectionState.DISCONNECTED
        self.conversation_state = ConversationState.IDLE
        self.session_id: Optional[str] = None

        # WebSocket
        self._ws = None
        self._ws_task: Optional[asyncio.Task] = None
        self._send_queue: asyncio.Queue = None
        self._receive_task: Optional[asyncio.Task] = None
        self._send_task: Optional[asyncio.Task] = None

        # Audio buffers
        self._input_buffer = bytearray()
        self._output_buffer = deque(maxlen=1000)  # Chunks de sortie

        # Métriques
        self.latency = LatencyMetrics()

        # Callbacks
        self._callbacks: Dict[str, List[Callable]] = {
            'on_connected': [],
            'on_disconnected': [],
            'on_error': [],
            'on_audio_received': [],
            'on_transcript': [],
            'on_response_start': [],
            'on_response_end': [],
            'on_speech_started': [],
            'on_speech_stopped': [],
        }

        # Compteurs
        self._reconnect_attempts = 0
        self._audio_chunks_sent = 0
        self._audio_chunks_received = 0
        self._first_audio_received = False

        # Event loop
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None

    # -------------------------------------------------------------------------
    # Callbacks
    # -------------------------------------------------------------------------

    def on(self, event: str, callback: Callable):
        """Enregistre un callback pour un événement."""
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    def _emit(self, event: str, *args, **kwargs):
        """Émet un événement vers les callbacks."""
        for callback in self._callbacks.get(event, []):
            try:
                callback(*args, **kwargs)
            except Exception as e:
                logger.error(f"Erreur callback {event}: {e}")

    # -------------------------------------------------------------------------
    # Connexion
    # -------------------------------------------------------------------------

    def connect(self) -> bool:
        """
        Établit la connexion WebSocket (synchrone).
        Lance un thread pour la boucle asyncio.
        """
        if self.connection_state == ConnectionState.CONNECTED:
            logger.warning("Déjà connecté")
            return True

        if not self.config.api_key:
            logger.error("API key manquante")
            return False

        self.connection_state = ConnectionState.CONNECTING

        # Lancer le thread asyncio
        self._thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self._thread.start()

        # Attendre la connexion (avec timeout)
        timeout = 10.0
        start = time.time()
        while self.connection_state == ConnectionState.CONNECTING:
            if time.time() - start > timeout:
                logger.error("Timeout connexion")
                return False
            time.sleep(0.1)

        return self.connection_state == ConnectionState.CONNECTED

    def _run_async_loop(self):
        """Thread pour la boucle asyncio."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._loop.run_until_complete(self._async_connect())
        except Exception as e:
            logger.error(f"Erreur boucle async: {e}")
            self.connection_state = ConnectionState.ERROR

    async def _async_connect(self):
        """Connexion WebSocket asynchrone."""
        try:
            import websockets
        except ImportError:
            logger.error("websockets non installé: pip install websockets")
            self.connection_state = ConnectionState.ERROR
            return

        url = f"{OPENAI_REALTIME_URL}?model={self.config.model}"

        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "OpenAI-Beta": "realtime=v1"
        }

        try:
            logger.info(f"Connexion à {url}...")

            self._ws = await websockets.connect(
                url,
                extra_headers=headers,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=5
            )

            self._send_queue = asyncio.Queue()

            self.connection_state = ConnectionState.CONNECTED
            self._reconnect_attempts = 0
            logger.info("Connecté à OpenAI Realtime")

            self._emit('on_connected')

            # Configurer la session
            await self._configure_session()

            # Lancer les tâches de réception/envoi
            self._receive_task = asyncio.create_task(self._receive_loop())
            self._send_task = asyncio.create_task(self._send_loop())

            # Attendre que les tâches se terminent
            await asyncio.gather(self._receive_task, self._send_task)

        except Exception as e:
            logger.error(f"Erreur connexion: {e}")
            self.connection_state = ConnectionState.ERROR
            self._emit('on_error', str(e))

            # Reconnexion automatique
            if self.config.auto_reconnect:
                await self._handle_reconnect()

    async def _configure_session(self):
        """Configure la session après connexion."""
        session_config = {
            "type": "session.update",
            "session": {
                "modalities": self.config.modalities,
                "voice": self.config.voice,
                "input_audio_format": self.config.input_audio_format,
                "output_audio_format": self.config.output_audio_format,
                "turn_detection": {
                    "type": self.config.turn_detection_type,
                    "threshold": self.config.turn_detection_threshold,
                    "prefix_padding_ms": self.config.turn_detection_prefix_padding_ms,
                    "silence_duration_ms": self.config.turn_detection_silence_duration_ms
                }
            }
        }

        # Ajouter instructions si présentes
        if self.config.instructions:
            session_config["session"]["instructions"] = self.config.instructions

        await self._ws.send(json.dumps(session_config))
        logger.info("Session configurée")

    async def _handle_reconnect(self):
        """Gère la reconnexion automatique."""
        if self._reconnect_attempts >= self.config.max_reconnect_attempts:
            logger.error("Max reconnexions atteint")
            self.connection_state = ConnectionState.ERROR
            return

        self._reconnect_attempts += 1
        self.connection_state = ConnectionState.RECONNECTING

        delay = self.config.reconnect_delay_ms / 1000 * self._reconnect_attempts
        logger.info(f"Reconnexion dans {delay:.1f}s (tentative {self._reconnect_attempts})")

        await asyncio.sleep(delay)
        await self._async_connect()

    def disconnect(self):
        """Ferme la connexion."""
        self.connection_state = ConnectionState.DISCONNECTED

        if self._receive_task:
            self._receive_task.cancel()
        if self._send_task:
            self._send_task.cancel()

        if self._ws:
            asyncio.run_coroutine_threadsafe(self._ws.close(), self._loop)

        self._emit('on_disconnected')
        logger.info("Déconnecté")

    # -------------------------------------------------------------------------
    # Envoi Audio
    # -------------------------------------------------------------------------

    def send_audio(self, audio_bytes: bytes):
        """
        Envoie de l'audio vers OpenAI (thread-safe).
        L'audio doit être en PCM16 24kHz mono.

        Args:
            audio_bytes: Audio PCM16 24kHz mono
        """
        if self.connection_state != ConnectionState.CONNECTED:
            return

        # Ajouter au buffer
        self._input_buffer.extend(audio_bytes)

        # Envoyer par chunks de CHUNK_BYTES
        while len(self._input_buffer) >= CHUNK_BYTES:
            chunk = bytes(self._input_buffer[:CHUNK_BYTES])
            del self._input_buffer[:CHUNK_BYTES]

            # Encoder en base64
            chunk_b64 = base64.b64encode(chunk).decode('utf-8')

            # Message API
            message = {
                "type": "input_audio_buffer.append",
                "audio": chunk_b64
            }

            # Mettre en queue pour envoi async
            if self._send_queue and self._loop:
                asyncio.run_coroutine_threadsafe(
                    self._send_queue.put(message),
                    self._loop
                )

            self._audio_chunks_sent += 1

    def commit_audio(self):
        """
        Signale la fin de l'audio d'entrée (commit buffer).
        Utile si turn_detection est désactivé.
        """
        if self.connection_state != ConnectionState.CONNECTED:
            return

        # Envoyer le reste du buffer
        if self._input_buffer:
            chunk_b64 = base64.b64encode(bytes(self._input_buffer)).decode('utf-8')
            message = {
                "type": "input_audio_buffer.append",
                "audio": chunk_b64
            }
            asyncio.run_coroutine_threadsafe(
                self._send_queue.put(message),
                self._loop
            )
            self._input_buffer.clear()

        # Commit
        commit_message = {"type": "input_audio_buffer.commit"}
        asyncio.run_coroutine_threadsafe(
            self._send_queue.put(commit_message),
            self._loop
        )

        # Enregistrer fin de parole pour latence
        self.latency.record_speech_end()

    def cancel_response(self):
        """Annule la réponse en cours (interruption)."""
        if self.connection_state != ConnectionState.CONNECTED:
            return

        message = {"type": "response.cancel"}
        asyncio.run_coroutine_threadsafe(
            self._send_queue.put(message),
            self._loop
        )

    async def _send_loop(self):
        """Boucle d'envoi des messages."""
        try:
            while self.connection_state == ConnectionState.CONNECTED:
                message = await self._send_queue.get()

                if self._ws:
                    await self._ws.send(json.dumps(message))

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Erreur envoi: {e}")

    # -------------------------------------------------------------------------
    # Réception Audio
    # -------------------------------------------------------------------------

    def get_output_audio(self) -> Optional[bytes]:
        """
        Récupère le prochain chunk audio de sortie.
        Retourne None si pas d'audio disponible.

        Returns:
            Audio PCM16 48kHz stéréo (format Pepper) ou None
        """
        if self._output_buffer:
            return self._output_buffer.popleft()
        return None

    def get_all_output_audio(self) -> bytes:
        """Récupère tout l'audio de sortie disponible."""
        result = bytearray()
        while self._output_buffer:
            result.extend(self._output_buffer.popleft())
        return bytes(result)

    def has_output_audio(self) -> bool:
        """Vérifie s'il y a de l'audio en attente."""
        return len(self._output_buffer) > 0

    async def _receive_loop(self):
        """Boucle de réception des messages."""
        try:
            async for message in self._ws:
                await self._handle_message(message)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Erreur réception: {e}")
            self.connection_state = ConnectionState.ERROR

            if self.config.auto_reconnect:
                await self._handle_reconnect()

    async def _handle_message(self, raw_message: str):
        """Traite un message reçu."""
        try:
            message = json.loads(raw_message)
            msg_type = message.get("type", "")

            # Session créée
            if msg_type == "session.created":
                self.session_id = message.get("session", {}).get("id")
                logger.info(f"Session créée: {self.session_id}")

            # Session mise à jour
            elif msg_type == "session.updated":
                logger.debug("Session mise à jour")

            # Début de réponse
            elif msg_type == "response.created":
                self.conversation_state = ConversationState.PROCESSING
                self._first_audio_received = False
                self._emit('on_response_start')

            # Audio delta (streaming)
            elif msg_type == "response.audio.delta":
                audio_b64 = message.get("delta", "")
                if audio_b64:
                    # Décoder base64
                    audio_24k = base64.b64decode(audio_b64)

                    # Mesure latence (premier byte)
                    if not self._first_audio_received:
                        self._first_audio_received = True
                        self.latency.record_first_audio()
                        logger.info(f"TTFB: {self.latency.time_to_first_byte_ms:.0f}ms")

                    # Convertir pour Pepper (24kHz mono → 48kHz stéréo)
                    audio_pepper = AudioConverter.convert_for_pepper(audio_24k)

                    # Ajouter au buffer de sortie
                    self._output_buffer.append(audio_pepper)
                    self._audio_chunks_received += 1

                    # Callback
                    self._emit('on_audio_received', audio_pepper)

            # Audio terminé
            elif msg_type == "response.audio.done":
                self.conversation_state = ConversationState.IDLE
                logger.debug("Audio réponse terminé")

            # Transcription
            elif msg_type == "response.audio_transcript.delta":
                transcript = message.get("delta", "")
                if transcript:
                    self._emit('on_transcript', transcript)

            # Fin de réponse
            elif msg_type == "response.done":
                self.conversation_state = ConversationState.IDLE
                self._emit('on_response_end')

            # Détection parole (VAD)
            elif msg_type == "input_audio_buffer.speech_started":
                self.conversation_state = ConversationState.LISTENING
                self._emit('on_speech_started')
                logger.debug("Parole détectée")

            elif msg_type == "input_audio_buffer.speech_stopped":
                self.latency.record_speech_end()
                self._emit('on_speech_stopped')
                logger.debug("Fin parole détectée")

            # Erreur
            elif msg_type == "error":
                error = message.get("error", {})
                error_msg = error.get("message", "Unknown error")
                logger.error(f"Erreur API: {error_msg}")
                self._emit('on_error', error_msg)

            # Rate limit
            elif msg_type == "rate_limits.updated":
                logger.debug(f"Rate limits: {message.get('rate_limits', [])}")

        except json.JSONDecodeError as e:
            logger.error(f"Erreur parsing JSON: {e}")
        except Exception as e:
            logger.error(f"Erreur traitement message: {e}")

    # -------------------------------------------------------------------------
    # Utilitaires
    # -------------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques."""
        return {
            'connection_state': self.connection_state.value,
            'conversation_state': self.conversation_state.value,
            'session_id': self.session_id,
            'audio_chunks_sent': self._audio_chunks_sent,
            'audio_chunks_received': self._audio_chunks_received,
            'output_buffer_size': len(self._output_buffer),
            'latency_ttfb_last_ms': self.latency.time_to_first_byte_ms,
            'latency_ttfb_avg_ms': self.latency.get_avg_ttfb(),
            'reconnect_attempts': self._reconnect_attempts
        }

    def is_connected(self) -> bool:
        """Vérifie si connecté."""
        return self.connection_state == ConnectionState.CONNECTED


# =============================================================================
# PROMPT SYSTÈME PARAPHARMACIE
# =============================================================================

PARAPHARMACIE_INSTRUCTIONS = """Tu es un assistant vocal pour une parapharmacie, spécialisé dans les produits capillaires.

RÈGLES STRICTES:
1. Tu réponds UNIQUEMENT aux questions sur les produits capillaires et la parapharmacie.
2. Tu NE DONNES JAMAIS de conseil médical, diagnostic, ou recommandation de traitement.
3. Si on te pose une question médicale, réponds: "Je ne peux pas répondre à cette question. Je vous invite à consulter le pharmacien."
4. Tes réponses doivent être CONCISES (2-3 phrases maximum) car tu es un assistant vocal.
5. Tu parles en français avec un ton professionnel mais accessible.
6. Tu peux parler du prix, de l'utilisation, des ingrédients, du type de cheveux adapté.

Tu NE DOIS PAS parler de:
- Problèmes de santé, maladies
- Traitements médicaux
- Effets secondaires
- Allergies (rediriger vers pharmacien)
- Interactions médicamenteuses"""


def create_parapharmacie_client(api_key: Optional[str] = None) -> OpenAIRealtimeClient:
    """
    Crée un client configuré pour le contexte parapharmacie.

    Args:
        api_key: Clé API OpenAI (ou variable OPENAI_API_KEY)

    Returns:
        Client configuré
    """
    config = RealtimeConfig(
        api_key=api_key or os.getenv("OPENAI_API_KEY", ""),
        voice="nova",  # Voix féminine claire
        instructions=PARAPHARMACIE_INSTRUCTIONS,
        turn_detection_type="server_vad",
        turn_detection_threshold=0.5,
        turn_detection_silence_duration_ms=700  # 700ms de silence = fin de phrase
    )

    return OpenAIRealtimeClient(config)


# =============================================================================
# TEST
# =============================================================================

if __name__ == "__main__":
    import sys

    print("=" * 60)
    print("TEST MODULE OPENAI REALTIME")
    print("=" * 60)

    # Vérifier API key
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("\n[ERREUR] Variable OPENAI_API_KEY non définie")
        print("Définissez-la avec: export OPENAI_API_KEY='sk-...'")
        sys.exit(1)

    print(f"\n[INFO] API key détectée: {api_key[:10]}...")

    # Créer le client
    print("\n[TEST] Création du client parapharmacie...")
    client = create_parapharmacie_client()

    # Callbacks
    def on_connected():
        print("[EVENT] Connecté!")

    def on_audio_received(audio):
        print(f"[EVENT] Audio reçu: {len(audio)} bytes")

    def on_transcript(text):
        print(f"[EVENT] Transcription: {text}")

    def on_error(error):
        print(f"[EVENT] Erreur: {error}")

    client.on('on_connected', on_connected)
    client.on('on_audio_received', on_audio_received)
    client.on('on_transcript', on_transcript)
    client.on('on_error', on_error)

    # Connexion
    print("\n[TEST] Connexion...")
    if client.connect():
        print("[OK] Connexion réussie!")

        # Attendre un peu
        print("\n[INFO] Client connecté. Stats:")
        time.sleep(2)

        stats = client.get_stats()
        for k, v in stats.items():
            print(f"  {k}: {v}")

        # Test envoi audio (silence)
        print("\n[TEST] Envoi audio silence (1s)...")
        silence = bytes(CHUNK_BYTES * 10)  # 1 seconde de silence
        client.send_audio(silence)

        time.sleep(3)

        print("\n[INFO] Stats après envoi:")
        stats = client.get_stats()
        for k, v in stats.items():
            print(f"  {k}: {v}")

        # Déconnexion
        print("\n[TEST] Déconnexion...")
        client.disconnect()

    else:
        print("[ERREUR] Connexion échouée")

    print("\n" + "=" * 60)
    print("TEST TERMINÉ")
    print("=" * 60)
