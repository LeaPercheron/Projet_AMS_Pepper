#!/usr/bin/env python3
# Phase 9 - Orchestrateur (State Machine)

import os
import asyncio
import time
import json
import wave
import struct
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Callable, Set
from enum import Enum, auto
from collections import deque
import logging

# Configuration logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Orchestrator")


# ÉTATS DE LA MACHINE

class State(Enum):
    # États de la machine à états.
    IDLE = auto()              # En attente, pas de client
    GREETING = auto()          # Salutation du client
    AWAITING_INTENT = auto()   # Attente de l'intention du client
    SCANNING_PRODUCT = auto()  # Scan visuel du produit
    CONFIRMING_TOP3 = auto()   # Confirmation parmi Top-3
    SCANNING_BARCODE = auto()  # Scan code-barres dédié
    DISPLAYING_INFO = auto()   # Affichage info produit
    CONVERSING = auto()        # Conversation avec le client
    ADVISING = auto()          # Conseil en cours
    ENDING = auto()            # Fin de l'interaction
    ERROR = auto()             # État d'erreur


class Event(Enum):
    # Événements déclencheurs de transitions.
    # Présence
    PERSON_DETECTED = auto()
    PERSON_LEFT = auto()

    # Audio
    SPEECH_DETECTED = auto()
    SPEECH_ENDED = auto()
    INTENT_RECOGNIZED = auto()

    # Vision
    PRODUCT_SHOWN = auto()
    BARCODE_DETECTED = auto()
    VLM_HIGH_CONFIDENCE = auto()
    VLM_MEDIUM_CONFIDENCE = auto()
    VLM_LOW_CONFIDENCE = auto()
    VLM_FAILED = auto()

    # Interaction
    USER_CONFIRMED = auto()
    USER_DENIED = auto()
    USER_SELECTED = auto()
    QUESTION_ASKED = auto()
    GOODBYE_DETECTED = auto()

    # Système
    TIMEOUT = auto()
    ERROR_OCCURRED = auto()
    NETWORK_ERROR = auto()
    RECOVERY_COMPLETE = auto()

    # Sécurité
    SECURITY_ALERT = auto()


# CONFIGURATION

@dataclass
class OrchestratorConfig:
    # Configuration de l'orchestrateur.
    # Timeouts (en secondes)
    idle_timeout: float = 60.0      # Timeout inactivité
    greeting_timeout: float = 10.0   # Timeout salutation
    intent_timeout: float = 30.0     # Timeout attente intention
    scan_timeout: float = 15.0       # Timeout scan produit
    confirm_timeout: float = 20.0    # Timeout confirmation
    conversation_timeout: float = 45.0  # Timeout conversation

    # LEDs
    led_fade_duration_ms: int = 300  # Durée fade LEDs

    # Queues
    max_queue_size: int = 100

    # Mode
    simulation_mode: bool = False
    log_transitions: bool = True


# COULEURS LEDs PAR ÉTAT

LED_COLORS = {
    State.IDLE: (0.0, 0.0, 1.0),        # Bleu - en attente
    State.GREETING: (0.0, 1.0, 0.0),     # Vert - accueil
    State.AWAITING_INTENT: (1.0, 1.0, 1.0),  # Blanc - écoute
    State.SCANNING_PRODUCT: (0.5, 0.0, 1.0),  # Violet - scan
    State.CONFIRMING_TOP3: (1.0, 0.5, 0.0),   # Orange - confirmation
    State.SCANNING_BARCODE: (0.5, 0.0, 1.0),  # Violet - scan
    State.DISPLAYING_INFO: (0.0, 1.0, 0.0),   # Vert - info
    State.CONVERSING: (1.0, 1.0, 1.0),        # Blanc - conversation
    State.ADVISING: (0.0, 1.0, 0.5),          # Turquoise - conseil
    State.ENDING: (0.0, 0.0, 1.0),            # Bleu - fin
    State.ERROR: (1.0, 0.0, 0.0),             # Rouge - erreur
}


# MICRO-PHRASES

MICRO_PHRASES = {
    "looking": [
        "Je regarde...",
        "Un instant...",
        "Je vérifie...",
    ],
    "thinking": [
        "Hmm...",
        "Voyons voir...",
        "Alors...",
    ],
    "understanding": [
        "D'accord.",
        "Je comprends.",
        "Très bien.",
    ],
    "responding": [
        "Je vais te répondre.",
        "Voici ce que je peux te dire.",
        "Alors...",
    ],
    "asking_barcode": [
        "Peux-tu me montrer le code-barres ?",
        "Montre-moi le code-barres s'il te plaît.",
    ],
    "confirming": [
        "C'est bien ça ?",
        "Tu confirmes ?",
    ],
    "greeting": [
        "Bonjour ! Je suis Pepper, l'assistant du rayon capillaire.",
        "Salut ! Comment puis-je t'aider ?",
    ],
    "goodbye": [
        "Au revoir ! À bientôt !",
        "Bonne journée !",
    ],
    "error": [
        "Désolé, j'ai un petit souci technique.",
        "Un instant, je me reconnecte...",
    ],
    "fallback": [
        "Je n'ai pas bien compris. Tu peux répéter ?",
        "Peux-tu reformuler ta question ?",
    ],
}


# CONTEXTE D'INTERACTION

@dataclass
class InteractionContext:
    # Contexte de l'interaction en cours.
    # Session
    session_id: str = ""
    session_start: float = 0.0

    # Client
    person_detected: bool = False
    last_activity: float = 0.0

    # Produit
    current_product_id: str = ""
    current_product_name: str = ""
    current_ean: str = ""
    vlm_confidence: float = 0.0
    top3_candidates: List[Dict] = field(default_factory=list)

    # Conversation
    last_user_input: str = ""
    last_intent: str = ""
    conversation_history: List[Dict] = field(default_factory=list)

    # Sécurité
    security_alert_active: bool = False

    def reset(self):
        # Réinitialise le contexte.
        self.session_id = ""
        self.session_start = 0.0
        self.person_detected = False
        self.current_product_id = ""
        self.current_product_name = ""
        self.current_ean = ""
        self.vlm_confidence = 0.0
        self.top3_candidates = []
        self.last_user_input = ""
        self.last_intent = ""
        self.conversation_history = []
        self.security_alert_active = False


# MACHINE À ÉTATS

class StateMachine:
    # Machine à états pour l'orchestrateur.

    def __init__(self, config: OrchestratorConfig):
        # Initialise l'objet.
        self.config = config
        self._state = State.IDLE
        self._previous_state = State.IDLE
        self._state_enter_time = time.time()

        # Transitions autorisées: (état_actuel, événement) -> état_suivant
        self._transitions: Dict[tuple, State] = self._build_transitions()

        # Callbacks
        self._on_enter_callbacks: Dict[State, List[Callable]] = {s: [] for s in State}
        self._on_exit_callbacks: Dict[State, List[Callable]] = {s: [] for s in State}

        # Historique
        self._history: deque = deque(maxlen=50)

    def _build_transitions(self) -> Dict[tuple, State]:
        # Définit toutes les transitions possibles.
        return {
            # IDLE
            (State.IDLE, Event.PERSON_DETECTED): State.GREETING,

            # GREETING
            (State.GREETING, Event.SPEECH_DETECTED): State.AWAITING_INTENT,
            (State.GREETING, Event.PRODUCT_SHOWN): State.SCANNING_PRODUCT,
            (State.GREETING, Event.PERSON_LEFT): State.IDLE,
            (State.GREETING, Event.TIMEOUT): State.IDLE,

            # AWAITING_INTENT
            (State.AWAITING_INTENT, Event.INTENT_RECOGNIZED): State.CONVERSING,
            (State.AWAITING_INTENT, Event.PRODUCT_SHOWN): State.SCANNING_PRODUCT,
            (State.AWAITING_INTENT, Event.QUESTION_ASKED): State.CONVERSING,
            (State.AWAITING_INTENT, Event.GOODBYE_DETECTED): State.ENDING,
            (State.AWAITING_INTENT, Event.PERSON_LEFT): State.IDLE,
            (State.AWAITING_INTENT, Event.TIMEOUT): State.ENDING,
            (State.AWAITING_INTENT, Event.SECURITY_ALERT): State.ADVISING,

            # SCANNING_PRODUCT
            (State.SCANNING_PRODUCT, Event.VLM_HIGH_CONFIDENCE): State.DISPLAYING_INFO,
            (State.SCANNING_PRODUCT, Event.VLM_MEDIUM_CONFIDENCE): State.CONFIRMING_TOP3,
            (State.SCANNING_PRODUCT, Event.VLM_LOW_CONFIDENCE): State.SCANNING_BARCODE,
            (State.SCANNING_PRODUCT, Event.VLM_FAILED): State.SCANNING_BARCODE,
            (State.SCANNING_PRODUCT, Event.BARCODE_DETECTED): State.DISPLAYING_INFO,
            (State.SCANNING_PRODUCT, Event.TIMEOUT): State.AWAITING_INTENT,
            (State.SCANNING_PRODUCT, Event.SECURITY_ALERT): State.ADVISING,

            # CONFIRMING_TOP3
            (State.CONFIRMING_TOP3, Event.USER_SELECTED): State.DISPLAYING_INFO,
            (State.CONFIRMING_TOP3, Event.USER_DENIED): State.SCANNING_BARCODE,
            (State.CONFIRMING_TOP3, Event.BARCODE_DETECTED): State.DISPLAYING_INFO,
            (State.CONFIRMING_TOP3, Event.TIMEOUT): State.SCANNING_BARCODE,

            # SCANNING_BARCODE
            (State.SCANNING_BARCODE, Event.BARCODE_DETECTED): State.DISPLAYING_INFO,
            (State.SCANNING_BARCODE, Event.TIMEOUT): State.AWAITING_INTENT,
            (State.SCANNING_BARCODE, Event.SECURITY_ALERT): State.ADVISING,

            # DISPLAYING_INFO
            (State.DISPLAYING_INFO, Event.QUESTION_ASKED): State.CONVERSING,
            (State.DISPLAYING_INFO, Event.PRODUCT_SHOWN): State.SCANNING_PRODUCT,
            (State.DISPLAYING_INFO, Event.GOODBYE_DETECTED): State.ENDING,
            (State.DISPLAYING_INFO, Event.TIMEOUT): State.AWAITING_INTENT,

            # CONVERSING
            (State.CONVERSING, Event.QUESTION_ASKED): State.ADVISING,
            (State.CONVERSING, Event.PRODUCT_SHOWN): State.SCANNING_PRODUCT,
            (State.CONVERSING, Event.GOODBYE_DETECTED): State.ENDING,
            (State.CONVERSING, Event.TIMEOUT): State.AWAITING_INTENT,
            (State.CONVERSING, Event.SECURITY_ALERT): State.ADVISING,

            # ADVISING
            (State.ADVISING, Event.SPEECH_ENDED): State.AWAITING_INTENT,
            (State.ADVISING, Event.QUESTION_ASKED): State.CONVERSING,
            (State.ADVISING, Event.GOODBYE_DETECTED): State.ENDING,
            (State.ADVISING, Event.TIMEOUT): State.AWAITING_INTENT,

            # ENDING
            (State.ENDING, Event.PERSON_LEFT): State.IDLE,
            (State.ENDING, Event.TIMEOUT): State.IDLE,
            (State.ENDING, Event.PERSON_DETECTED): State.GREETING,

            # ERROR (peut transiter depuis n'importe quel état)
            (State.ERROR, Event.RECOVERY_COMPLETE): State.IDLE,
            (State.ERROR, Event.TIMEOUT): State.IDLE,
        }

        # Ajouter transitions d'erreur depuis tous les états
        for state in State:
            if state != State.ERROR:
                self._transitions[(state, Event.ERROR_OCCURRED)] = State.ERROR
                self._transitions[(state, Event.NETWORK_ERROR)] = State.ERROR

    @property
    def state(self) -> State:
        # État actuel.
        return self._state

    @property
    def previous_state(self) -> State:
        # État précédent.
        return self._previous_state

    @property
    def time_in_state(self) -> float:
        # Temps passé dans l'état actuel (secondes).
        return time.time() - self._state_enter_time

    def can_transition(self, event: Event) -> bool:
        # Vérifie si une transition est possible.
        return (self._state, event) in self._transitions

    def process_event(self, event: Event) -> bool:
        # Traite un événement et effectue la transition si possible.
        key = (self._state, event)

        if key not in self._transitions:
            logger.debug(f"Transition non définie: {self._state.name} + {event.name}")
            return False

        new_state = self._transitions[key]

        # Callbacks de sortie
        for callback in self._on_exit_callbacks[self._state]:
            try:
                callback(self._state, event)
            except Exception as e:
                logger.error(f"Erreur callback exit: {e}")

        # Enregistrer historique
        self._history.append({
            "from": self._state.name,
            "event": event.name,
            "to": new_state.name,
            "timestamp": time.time()
        })

        # Transition
        self._previous_state = self._state
        self._state = new_state
        self._state_enter_time = time.time()

        if self.config.log_transitions:
            logger.info(f"Transition: {self._previous_state.name} --[{event.name}]--> {self._state.name}")

        # Callbacks d'entrée
        for callback in self._on_enter_callbacks[self._state]:
            try:
                callback(self._state, event)
            except Exception as e:
                logger.error(f"Erreur callback enter: {e}")

        return True

    def on_enter(self, state: State, callback: Callable):
        # Enregistre un callback d'entrée dans un état.
        self._on_enter_callbacks[state].append(callback)

    def on_exit(self, state: State, callback: Callable):
        # Enregistre un callback de sortie d'un état.
        self._on_exit_callbacks[state].append(callback)

    def get_history(self) -> List[Dict]:
        # Retourne l'historique des transitions.
        return list(self._history)

    def reset(self):
        # Réinitialise la machine à IDLE.
        self._previous_state = self._state
        self._state = State.IDLE
        self._state_enter_time = time.time()
        logger.info("State machine reset to IDLE")


# ORCHESTRATEUR

class Orchestrator:
    # Orchestrateur principal coordonnant tous les modules.

    def __init__(self, config: Optional[OrchestratorConfig] = None):
        # Initialise l'objet.
        self.config = config or OrchestratorConfig()

        # Machine à états
        self.state_machine = StateMachine(self.config)

        # Contexte
        self.context = InteractionContext()

        # Queues pour communication inter-tâches
        self._event_queue: asyncio.Queue = None
        self._audio_queue: asyncio.Queue = None
        self._video_queue: asyncio.Queue = None

        # Tâches asynchrones
        self._tasks: List[asyncio.Task] = []
        self._running = False

        # Modules externes (à injecter)
        self._audio_module = None
        self._video_module = None
        self._vision_module = None
        self._database_module = None
        self._security_module = None
        self._realtime_client = None
        self._robot_actions = None

        # Micro-phrases pré-chargées
        self._phrases_cache: Dict[str, List[str]] = MICRO_PHRASES.copy()

        # Statistiques
        self._stats = {
            "sessions": 0,
            "products_scanned": 0,
            "questions_answered": 0,
            "security_alerts": 0,
            "errors": 0
        }

        # Enregistrer callbacks de transition
        self._setup_state_callbacks()

    def _setup_state_callbacks(self):
        # Configure les callbacks pour chaque état.
        # Entrée dans GREETING
        self.state_machine.on_enter(State.GREETING, self._on_enter_greeting)

        # Entrée dans SCANNING_PRODUCT
        self.state_machine.on_enter(State.SCANNING_PRODUCT, self._on_enter_scanning)

        # Entrée dans DISPLAYING_INFO
        self.state_machine.on_enter(State.DISPLAYING_INFO, self._on_enter_displaying)

        # Entrée dans ERROR
        self.state_machine.on_enter(State.ERROR, self._on_enter_error)

        # Entrée dans ENDING
        self.state_machine.on_enter(State.ENDING, self._on_enter_ending)

        # Sortie de IDLE (début session)
        self.state_machine.on_exit(State.IDLE, self._on_exit_idle)

    # INJECTION MODULES

    def set_audio_module(self, module):
        # Injecte le module audio.
        self._audio_module = module

    def set_video_module(self, module):
        # Injecte le module vidéo.
        self._video_module = module

    def set_vision_module(self, module):
        # Injecte le module vision.
        self._vision_module = module

    def set_database_module(self, module):
        # Injecte le module base de données.
        self._database_module = module

    def set_security_module(self, module):
        # Injecte le module sécurité.
        self._security_module = module

    def set_realtime_client(self, client):
        # Injecte le client OpenAI Realtime.
        self._realtime_client = client

    def set_robot_actions(self, actions):
        # Injecte les actions robot.
        self._robot_actions = actions

    # CALLBACKS D'ÉTAT

    def _on_exit_idle(self, state: State, event: Event):
        # Début d'une nouvelle session.
        self.context.session_id = f"session_{int(time.time())}"
        self.context.session_start = time.time()
        self._stats["sessions"] += 1
        logger.info(f"Nouvelle session: {self.context.session_id}")

    def _on_enter_greeting(self, state: State, event: Event):
        # Salutation du client.
        asyncio.create_task(self._play_phrase("greeting"))
        asyncio.create_task(self._set_leds(LED_COLORS[State.GREETING]))

    def _on_enter_scanning(self, state: State, event: Event):
        # Début du scan produit.
        asyncio.create_task(self._play_phrase("looking"))
        asyncio.create_task(self._set_leds(LED_COLORS[State.SCANNING_PRODUCT]))
        self._stats["products_scanned"] += 1

    def _on_enter_displaying(self, state: State, event: Event):
        # Affichage info produit.
        asyncio.create_task(self._set_leds(LED_COLORS[State.DISPLAYING_INFO]))

    def _on_enter_error(self, state: State, event: Event):
        # Entrée en état d'erreur.
        asyncio.create_task(self._play_phrase("error"))
        asyncio.create_task(self._set_leds(LED_COLORS[State.ERROR]))
        self._stats["errors"] += 1

    def _on_enter_ending(self, state: State, event: Event):
        # Fin de l'interaction.
        asyncio.create_task(self._play_phrase("goodbye"))
        asyncio.create_task(self._set_leds(LED_COLORS[State.ENDING]))

    # ACTIONS

    async def _play_phrase(self, category: str, index: int = 0):
        # Joue une micro-phrase pré-générée.
        if category not in self._phrases_cache:
            return

        phrases = self._phrases_cache[category]
        if not phrases:
            return

        import random
        phrase = random.choice(phrases) if index == 0 else phrases[min(index - 1, len(phrases) - 1)]

        logger.debug(f"Phrase: {phrase}")

        # TODO: Lecture audio réelle
        # if self._robot_actions:
        #     await self._robot_actions.say(phrase)

    async def _set_leds(self, color: tuple, fade_ms: int = None):
        # Configure les LEDs avec fade.
        fade_ms = fade_ms or self.config.led_fade_duration_ms
        logger.debug(f"LEDs: RGB{color} (fade {fade_ms}ms)")

        # TODO: Commande LEDs réelle
        # if self._robot_actions:
        #     await self._robot_actions.fade_leds(color, fade_ms)

    # GESTION ÉVÉNEMENTS

    async def send_event(self, event: Event, data: Dict = None):
        # Envoie un événement à la machine à états.
        if self._event_queue:
            await self._event_queue.put((event, data or {}))

    def send_event_sync(self, event: Event, data: Dict = None):
        # Version synchrone de send_event (pour callbacks).
        if self._event_queue:
            try:
                self._event_queue.put_nowait((event, data or {}))
            except asyncio.QueueFull:
                logger.warning(f"Event queue full, dropping {event.name}")

    async def _process_events(self):
        # Tâche de traitement des événements.
        while self._running:
            try:
                event, data = await asyncio.wait_for(
                    self._event_queue.get(),
                    timeout=0.1
                )

                # Mettre à jour le contexte selon les données
                self._update_context(event, data)

                # Traiter l'événement
                self.state_machine.process_event(event)

                # Mettre à jour l'activité
                self.context.last_activity = time.time()

            except asyncio.TimeoutError:
                # Vérifier timeout d'inactivité
                await self._check_timeout()

            except Exception as e:
                logger.error(f"Erreur traitement événement: {e}")

    def _update_context(self, event: Event, data: Dict):
        # Met à jour le contexte selon l'événement.
        if event == Event.PERSON_DETECTED:
            self.context.person_detected = True

        elif event == Event.PERSON_LEFT:
            self.context.person_detected = False

        elif event == Event.SPEECH_DETECTED:
            self.context.last_user_input = data.get("text", "")

        elif event == Event.VLM_HIGH_CONFIDENCE:
            self.context.current_product_name = data.get("product_name", "")
            self.context.vlm_confidence = data.get("confidence", 0.0)

        elif event == Event.VLM_MEDIUM_CONFIDENCE:
            self.context.top3_candidates = data.get("candidates", [])
            self.context.vlm_confidence = data.get("confidence", 0.0)

        elif event == Event.BARCODE_DETECTED:
            self.context.current_ean = data.get("ean", "")

        elif event == Event.SECURITY_ALERT:
            self.context.security_alert_active = True
            self._stats["security_alerts"] += 1

    async def _check_timeout(self):
        # Vérifie les timeouts selon l'état actuel.
        state = self.state_machine.state
        time_in_state = self.state_machine.time_in_state

        timeout_map = {
            State.GREETING: self.config.greeting_timeout,
            State.AWAITING_INTENT: self.config.intent_timeout,
            State.SCANNING_PRODUCT: self.config.scan_timeout,
            State.CONFIRMING_TOP3: self.config.confirm_timeout,
            State.SCANNING_BARCODE: self.config.scan_timeout,
            State.CONVERSING: self.config.conversation_timeout,
            State.ADVISING: self.config.conversation_timeout,
            State.DISPLAYING_INFO: self.config.conversation_timeout,
            State.ENDING: 5.0,
            State.ERROR: 10.0,
        }

        timeout = timeout_map.get(state)
        if timeout and time_in_state > timeout:
            logger.info(f"Timeout dans état {state.name} ({time_in_state:.1f}s > {timeout}s)")
            self.state_machine.process_event(Event.TIMEOUT)

    # TÂCHES PARALLÈLES

    async def _monitor_presence(self):
        # Tâche de monitoring de présence.
        last_presence = False

        while self._running:
            try:
                # TODO: Vérifier présence réelle via capteurs Pepper
                # Pour simulation, on simule une présence stable
                presence = self.context.person_detected

                if presence != last_presence:
                    if presence:
                        await self.send_event(Event.PERSON_DETECTED)
                    else:
                        await self.send_event(Event.PERSON_LEFT)
                    last_presence = presence

                await asyncio.sleep(0.5)

            except Exception as e:
                logger.error(f"Erreur monitor_presence: {e}")
                await asyncio.sleep(1.0)

    async def _audio_stream_handler(self):
        # Tâche de gestion du flux audio.
        while self._running:
            try:
                if self._audio_queue:
                    audio_data = await asyncio.wait_for(
                        self._audio_queue.get(),
                        timeout=0.1
                    )

                    # Traiter les données audio
                    # TODO: Envoyer à OpenAI Realtime, détecter fin de parole, etc.

            except asyncio.TimeoutError:
                pass
            except Exception as e:
                logger.error(f"Erreur audio_stream: {e}")

    async def _video_stream_handler(self):
        # Tâche de gestion du flux vidéo.
        while self._running:
            try:
                if self._video_queue:
                    frame = await asyncio.wait_for(
                        self._video_queue.get(),
                        timeout=0.1
                    )

                    # Traiter la frame
                    # TODO: Détection produit, code-barres, etc.

            except asyncio.TimeoutError:
                pass
            except Exception as e:
                logger.error(f"Erreur video_stream: {e}")

    # GESTION ERREURS ET FALLBACKS

    async def _handle_network_error(self):
        # Gère une erreur réseau.
        logger.warning("Erreur réseau détectée")

        # Passer en mode dégradé
        await self.send_event(Event.NETWORK_ERROR)

        # TODO: Activer mode tablette
        # TODO: Tentative de reconnexion

    async def _handle_vlm_fallback(self):
        # Fallback VLM vers code-barres.
        logger.info("Fallback VLM → code-barres")
        self.state_machine.process_event(Event.VLM_FAILED)

    async def _attempt_recovery(self):
        # Tente une récupération après erreur.
        logger.info("Tentative de récupération...")

        # Réinitialiser le contexte
        self.context.reset()

        # Réinitialiser les modules si nécessaire
        # TODO: Reconnecter les modules

        await asyncio.sleep(2.0)

        # Signaler la récupération
        await self.send_event(Event.RECOVERY_COMPLETE)

    # CYCLE DE VIE

    async def start(self):
        # Démarre l'orchestrateur.
        logger.info("Démarrage de l'orchestrateur...")

        self._running = True

        # Créer les queues
        self._event_queue = asyncio.Queue(maxsize=self.config.max_queue_size)
        self._audio_queue = asyncio.Queue(maxsize=self.config.max_queue_size)
        self._video_queue = asyncio.Queue(maxsize=self.config.max_queue_size)

        # Démarrer les tâches
        self._tasks = [
            asyncio.create_task(self._process_events()),
            asyncio.create_task(self._monitor_presence()),
            asyncio.create_task(self._audio_stream_handler()),
            asyncio.create_task(self._video_stream_handler()),
        ]

        # LEDs initiales
        await self._set_leds(LED_COLORS[State.IDLE])

        logger.info("Orchestrateur démarré")

    async def stop(self):
        # Arrête l'orchestrateur.
        logger.info("Arrêt de l'orchestrateur...")

        self._running = False

        # Annuler les tâches
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self._tasks.clear()

        # Réinitialiser
        self.state_machine.reset()
        self.context.reset()

        logger.info("Orchestrateur arrêté")

    async def run(self):
        # Exécute l'orchestrateur (boucle principale).
        await self.start()

        try:
            # Garder l'orchestrateur en vie
            while self._running:
                await asyncio.sleep(1.0)

        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    # API PUBLIQUE

    @property
    def current_state(self) -> State:
        # État actuel.
        return self.state_machine.state

    def get_stats(self) -> Dict:
        # Retourne les statistiques.
        return {
            **self._stats,
            "current_state": self.state_machine.state.name,
            "time_in_state": self.state_machine.time_in_state,
            "session_id": self.context.session_id
        }

    def get_context(self) -> Dict:
        # Retourne le contexte actuel.
        return {
            "session_id": self.context.session_id,
            "person_detected": self.context.person_detected,
            "current_product": self.context.current_product_name,
            "current_ean": self.context.current_ean,
            "vlm_confidence": self.context.vlm_confidence,
            "last_input": self.context.last_user_input
        }


# TEST

async def test_orchestrator():
    # Test de l'orchestrateur.
    print("=" * 70)
    print("TEST ORCHESTRATEUR - PHASE 9")
    print("=" * 70)

    # Créer orchestrateur
    config = OrchestratorConfig(
        idle_timeout=10.0,
        greeting_timeout=5.0,
        simulation_mode=True
    )
    orchestrator = Orchestrator(config)

    # Démarrer
    await orchestrator.start()

    print(f"\n[1] État initial: {orchestrator.current_state.name}")

    # Simuler une interaction
    print("\n[2] Simulation d'interaction")
    print("-" * 50)

    # Personne détectée
    print("  → Personne détectée")
    await orchestrator.send_event(Event.PERSON_DETECTED)
    await asyncio.sleep(0.5)
    print(f"    État: {orchestrator.current_state.name}")

    # Parole détectée
    print("  → Parole détectée")
    await orchestrator.send_event(Event.SPEECH_DETECTED, {"text": "Bonjour"})
    await asyncio.sleep(0.5)
    print(f"    État: {orchestrator.current_state.name}")

    # Produit montré
    print("  → Produit montré")
    await orchestrator.send_event(Event.PRODUCT_SHOWN)
    await asyncio.sleep(0.5)
    print(f"    État: {orchestrator.current_state.name}")

    # VLM haute confiance
    print("  → VLM haute confiance")
    await orchestrator.send_event(Event.VLM_HIGH_CONFIDENCE, {
        "product_name": "Klorane Shampooing Camomille",
        "confidence": 0.92
    })
    await asyncio.sleep(0.5)
    print(f"    État: {orchestrator.current_state.name}")

    # Question
    print("  → Question posée")
    await orchestrator.send_event(Event.QUESTION_ASKED)
    await asyncio.sleep(0.5)
    print(f"    État: {orchestrator.current_state.name}")

    # Au revoir
    print("  → Au revoir détecté")
    await orchestrator.send_event(Event.GOODBYE_DETECTED)
    await asyncio.sleep(0.5)
    print(f"    État: {orchestrator.current_state.name}")

    # Personne partie
    print("  → Personne partie")
    await orchestrator.send_event(Event.PERSON_LEFT)
    await asyncio.sleep(0.5)
    print(f"    État: {orchestrator.current_state.name}")

    # Statistiques
    print("\n[3] Statistiques")
    print("-" * 50)
    stats = orchestrator.get_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")

    # Historique
    print("\n[4] Historique des transitions")
    print("-" * 50)
    for entry in orchestrator.state_machine.get_history():
        print(f"  {entry['from']} --[{entry['event']}]--> {entry['to']}")

    # Arrêter
    await orchestrator.stop()

    print("\n" + "=" * 70)


if __name__ == "__main__":
    asyncio.run(test_orchestrator())
