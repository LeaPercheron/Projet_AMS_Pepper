#!/usr/bin/env python3
# Point d'Entree Principal - Parapharma Assistant

import asyncio
import argparse
import signal
import sys
import os
import socket
import urllib.request
import time
from pathlib import Path
from typing import Optional, Any, Dict, List, Tuple

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

# Ajouter le repertoire src au path
src_path = Path(__file__).parent.parent
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

# Charger automatiquement .env si python-dotenv est disponible.
if load_dotenv is not None:
    project_root = Path(__file__).resolve().parents[2]
    load_dotenv(project_root / ".env")
    load_dotenv()

from assistant.config import (
    Config, RunMode, get_config, reset_config,
    get_development_config, get_production_config, get_simulation_config
)
from assistant.logger import SystemLogger, LogEvent, get_logger


class PepperAssistant:
    # Assistant Parapharmacie Robotique - Systeme Integre.

    def __init__(self, config: Config, tablet_url_override: str = ""):
        # Initialise l'objet.
        self.config = config
        self.logger = SystemLogger(
            log_directory=config.logging.log_directory,
            file_prefix=config.logging.log_file_prefix,
            console_level=config.logging.console_level,
            file_level=config.logging.file_level
        )

        # Modules (initialises dans setup())
        self.adapter = None
        self.orchestrator = None
        self.openai_client = None
        self.http_fallback_client = None
        self.voice_fallback = None
        self.vision_pipeline = None
        self.database = None
        self.security_module = None
        self.tablet_server = None
        self._tablet_product_cls = None
        self._tablet_top3_cls = None

        # Etat
        self._running = False
        self._tasks = []
        self._shutdown_event = asyncio.Event()
        self._main_loop = None
        self._tablet_url_override = (tablet_url_override or "").strip()
        self._scan_lock = asyncio.Lock()

    async def setup(self):
        # Initialise tous les modules.
        self.logger.log_event(LogEvent.SYSTEM_START, {
            "mode": self.config.mode.value,
            "production": self.config.PRODUCTION_MODE
        })

        self.logger.log_info(f"Initialisation en mode {self.config.mode.value}...")

        await self._setup_adapter()

        await self._setup_database()

        await self._setup_security()

        await self._setup_vision()

        await self._setup_audio()

        await self._setup_tablet()

        await self._setup_orchestrator()

        await self._setup_voice_fallback()

        await self._setup_tablet_handlers()

        self.logger.log_event(LogEvent.CONFIG_LOADED, {
            "modules_loaded": self._get_loaded_modules()
        })

        self.logger.log_info("Tous les modules initialises")

    async def _setup_adapter(self):
        # Configure l'adaptateur robot.
        self.logger.log_info("Chargement adaptateur robot...")

        try:
            from assistant.adapters import get_adapter

            self.adapter = get_adapter(self.config)
            adapter_type = type(self.adapter).__name__

            if self.config.mode != RunMode.SIMULATION:
                if self.adapter.connect():
                    self.logger.log_info(f"  Adaptateur: {adapter_type} (connecte)")
                else:
                    self.logger.log_warning(f"  Adaptateur: {adapter_type} (echec connexion)")
            else:
                self.adapter.connect()
                self.logger.log_info(f"  Adaptateur: {adapter_type} (simulation)")

        except Exception as e:
            self.logger.log_error("Erreur chargement adaptateur", exception=e)

    async def _setup_database(self):
        # Configure le module base de donnees.
        self.logger.log_info("Chargement base de donnees...")

        try:
            from assistant.database import ProductDatabase

            db_path = self.config.database.db_path
            if Path(db_path).exists():
                self.database = ProductDatabase(db_path)
                product_count = self.database.count_products()
                self.logger.log_info(f"  Base de donnees: {product_count} produits")
            else:
                self.logger.log_warning(f"  Base de donnees non trouvee: {db_path}")

        except ImportError as e:
            self.logger.log_warning(f"Module database non disponible: {e}")
        except Exception as e:
            self.logger.log_error("Erreur chargement database", exception=e)

    async def _setup_security(self):
        # Configure le module securite.
        self.logger.log_info("Chargement module securite...")

        try:
            from assistant.safety import SecurityModule, SecurityConfig as SecConfig

            sec_config = SecConfig(
                strict_mode=self.config.security.strict_mode
            )
            self.security_module = SecurityModule(
                sec_config,
                blacklist_path=self.config.database.blacklist_path
            )

            self.logger.log_info("  Module securite: OK")

        except ImportError as e:
            self.logger.log_warning(f"Module securite non disponible: {e}")
        except Exception as e:
            self.logger.log_error("Erreur chargement securite", exception=e)

    async def _setup_vision(self):
        # Configure le module vision.
        if self.config.mode == RunMode.SIMULATION:
            self.logger.log_info("Vision: mode simulation (desactive)")
            return

        self.logger.log_info("Chargement module vision...")

        try:
            from assistant.vision import VisionModule, VisionConfig as VisConfig

            vision_config = VisConfig(
                camera_index=self.config.vision.camera_index,
                vlm_model=self.config.vision.vlm_model,
                confidence_high=self.config.vision.confidence_high,
                confidence_medium=self.config.vision.confidence_medium
            )

            self.vision_pipeline = VisionModule(
                vision_config,
                database_path=self.config.database.db_path
            )
            self.logger.log_info(f"  Vision: {self.config.vision.vlm_model}")

        except ImportError as e:
            self.logger.log_warning(f"Module vision non disponible: {e}")
        except Exception as e:
            self.logger.log_error("Erreur chargement vision", exception=e)

    async def _setup_audio(self):
        # Configure les modules audio (OpenAI + VAD).
        if self.config.mode == RunMode.SIMULATION:
            self.logger.log_info("Audio: mode simulation")
            return

        self.logger.log_info("Chargement module audio...")

        # Préparer le fallback HTTP (même si Realtime est indisponible).
        try:
            from assistant.llm import OpenAIHTTPFallbackClient

            if self.config.openai.api_key:
                fallback_model = (
                    os.getenv("OPENAI_HTTP_FALLBACK_MODEL", "").strip()
                    or self.config.openai.http_fallback_model
                )
                self.http_fallback_client = OpenAIHTTPFallbackClient(
                    api_key=self.config.openai.api_key,
                    model=fallback_model
                )
                self.logger.log_info(f"  OpenAI HTTP fallback: {fallback_model}")
            else:
                self.logger.log_warning("  OpenAI: Pas de cle API configuree")
        except ImportError as e:
            self.logger.log_warning(f"Module fallback HTTP non disponible: {e}")
        except Exception as e:
            self.logger.log_warning(f"  Fallback HTTP non initialisé: {e}")

        disable_realtime = os.getenv("OPENAI_REALTIME_DISABLED", "").strip().lower()
        if disable_realtime in {"1", "true", "yes", "on"}:
            self.logger.log_warning("  OpenAI Realtime desactive via OPENAI_REALTIME_DISABLED")
            return

        try:
            from assistant.realtime import OpenAIRealtimeClient, RealtimeConfig

            if self.config.openai.api_key:
                realtime_config = RealtimeConfig(
                    api_key=self.config.openai.api_key,
                    model=self.config.openai.model,
                    voice=self.config.openai.voice
                )

                self.openai_client = OpenAIRealtimeClient(realtime_config)
                self.logger.log_info(f"  OpenAI Realtime: {self.config.openai.model}")

        except ImportError as e:
            self.logger.log_warning(f"Module OpenAI non disponible: {e}")
        except Exception as e:
            self.logger.log_error("Erreur chargement audio", exception=e)

    async def _setup_tablet(self):
        # Configure le serveur tablette.
        self.logger.log_info("Chargement serveur tablette...")

        try:
            # Import depuis le dossier tablet
            tablet_path = Path(__file__).parent.parent.parent / "tablet"
            if tablet_path.exists():
                sys.path.insert(0, str(tablet_path))
                from server import (
                    TabletServer,
                    ServerConfig as TabletServerConfig,
                    Product as TabletProduct,
                    Top3Result as TabletTop3Result,
                )

                server_config = TabletServerConfig(
                    host=self.config.tablet.ws_host,
                    port=self.config.tablet.ws_port
                )
                self.tablet_server = TabletServer(config=server_config)
                self._tablet_product_cls = TabletProduct
                self._tablet_top3_cls = TabletTop3Result

                self.logger.log_info(
                    f"  Tablette WebSocket: ws://{self.config.tablet.ws_host}:"
                    f"{self.config.tablet.ws_port}"
                )
            else:
                self.logger.log_warning("  Dossier tablet/ non trouve")

        except ImportError as e:
            self.logger.log_warning(f"Module tablette non disponible: {e}")
        except Exception as e:
            self.logger.log_error("Erreur chargement tablette", exception=e)

    async def _setup_orchestrator(self):
        # Configure l'orchestrateur.
        self.logger.log_info("Chargement orchestrateur...")

        try:
            from assistant.orchestrator import Orchestrator, OrchestratorConfig as OrchConfig

            orch_config = OrchConfig(
                idle_timeout=self.config.orchestrator.idle_timeout,
                greeting_timeout=self.config.orchestrator.greeting_timeout,
                intent_timeout=self.config.orchestrator.intent_timeout,
                scan_timeout=self.config.orchestrator.scan_timeout,
                confirm_timeout=self.config.orchestrator.confirm_timeout,
                conversation_timeout=self.config.orchestrator.conversation_timeout,
                log_transitions=self.config.orchestrator.log_transitions
            )

            self.orchestrator = Orchestrator(orch_config)

            # Injecter les modules
            if self.database:
                self.orchestrator.set_database_module(self.database)
            if self.security_module:
                self.orchestrator.set_security_module(self.security_module)
            if self.vision_pipeline:
                self.orchestrator.set_vision_module(self.vision_pipeline)
            if self.openai_client:
                self.orchestrator.set_realtime_client(self.openai_client)
            if self.adapter:
                self.orchestrator.set_audio_module(self.adapter)
                self.orchestrator.set_video_module(self.adapter)
                self.orchestrator.set_robot_actions(self.adapter)

            self.logger.log_info("  Orchestrateur: OK")

        except ImportError as e:
            self.logger.log_warning(f"Module orchestrateur non disponible: {e}")
        except Exception as e:
            self.logger.log_error("Erreur chargement orchestrateur", exception=e)

    async def _setup_voice_fallback(self):
        # Configure le fallback vocal HTTP (micro -> transcription -> réponse -> TTS).
        if not self.http_fallback_client or not self.adapter or not self.orchestrator:
            return
        try:
            from assistant.llm import HTTPVoiceFallback, VoiceFallbackConfig

            transcription_model = (
                os.getenv("OPENAI_HTTP_TRANSCRIPTION_MODEL", "").strip()
                or self.config.openai.http_transcription_model
            )

            input_sr = getattr(getattr(self.adapter, "config", None), "sample_rate", None)
            if not input_sr:
                input_sr = self.config.audio.input_sample_rate

            input_ch = getattr(getattr(self.adapter, "config", None), "channels_in", None)
            if not input_ch:
                input_ch = self.config.audio.input_channels

            vf_config = VoiceFallbackConfig(
                input_sample_rate=int(input_sr),
                input_channels=int(input_ch),
                transcription_model=transcription_model,
                manual_trigger=True,
                listen_window_s=9.0
            )

            def _speak_blocking(answer_text: str):
                if self.adapter and hasattr(self.adapter, "say"):
                    # Bloquant pour réduire l'auto-capture.
                    self.adapter.say(answer_text, True)

            self.voice_fallback = HTTPVoiceFallback(
                api_key=self.config.openai.api_key,
                text_client=self.http_fallback_client,
                speak_callback=_speak_blocking,
                context_provider=lambda: self.orchestrator.get_context() if self.orchestrator else {},
                on_transcript=self._on_voice_fallback_transcript,
                on_answer=self._on_voice_fallback_answer,
                config=vf_config
            )
            self.voice_fallback.start()
            self.orchestrator.set_fallback_audio_handler(self.voice_fallback.ingest)
            self.logger.log_info(
                f"  Fallback vocal HTTP: actif (transcription={transcription_model})"
            )
        except Exception as e:
            self.logger.log_warning(f"  Fallback vocal HTTP non initialisé: {e}")

    def _on_voice_fallback_transcript(self, transcript: str):
        # Callback thread-safe: transcription utilisateur via fallback vocal.
        if not transcript:
            return
        if self.orchestrator:
            try:
                from assistant.orchestrator import Event
                self.orchestrator.send_event_sync(
                    Event.QUESTION_ASKED,
                    {"text": transcript, "source": "http_voice_fallback"}
                )
            except Exception:
                pass

    def _on_voice_fallback_answer(self, transcript: str, answer: str):
        # Callback thread-safe: publier la réponse sur tablette (si connectée).
        if not self.tablet_server or not self._main_loop:
            return
        try:
            if hasattr(self.tablet_server, "send_qa_answer"):
                fut = asyncio.run_coroutine_threadsafe(
                    self.tablet_server.send_qa_answer(True, transcript, answer),
                    self._main_loop
                )
                fut.result(timeout=2.0)
        except Exception:
            pass

    async def _setup_tablet_handlers(self):
        # Branche les commandes tablette custom.
        if not self.tablet_server:
            return
        try:
            self.tablet_server.register_handler("ask_question", self._handle_tablet_ask_question)
            self.tablet_server.register_handler("start_visual_scan", self._handle_tablet_start_visual_scan)
            self.tablet_server.register_handler("start_barcode_scan", self._handle_tablet_start_barcode_scan)
            self.tablet_server.register_handler("confirm_product", self._handle_tablet_confirm_product)
            self.tablet_server.register_handler("start_voice_question", self._handle_tablet_start_voice_question)
            self.logger.log_info(
                "  Tablette: handlers start_visual_scan/start_barcode_scan/start_voice_question actifs (ask_question désactivé)"
            )
        except Exception as e:
            self.logger.log_warning(f"  Tablette: handlers indisponibles ({e})")

    def _is_realtime_connected(self) -> bool:
        return bool(self.openai_client and self.openai_client.is_connected())

    @staticmethod
    def _extract_image_from_frame(frame_bytes: bytes):
        # Convertit bytes RGB bruts en image PIL.
        if not frame_bytes:
            return None
        data = bytes(frame_bytes)
        if len(data) < 3 or len(data) % 3 != 0:
            return None

        pixel_count = len(data) // 3
        known_sizes = (
            (640, 480),
            (320, 240),
            (1280, 960),
            (100, 100),
        )

        width = 0
        height = 0
        for w, h in known_sizes:
            if w * h == pixel_count:
                width, height = w, h
                break

        if not width:
            side = int(pixel_count ** 0.5)
            if side * side == pixel_count:
                width, height = side, side
            else:
                return None

        try:
            from PIL import Image
            return Image.frombytes("RGB", (width, height), data[: width * height * 3])
        except Exception:
            return None

    @staticmethod
    def _normalize_hair_type(value: Any) -> str:
        if isinstance(value, list):
            cleaned = [str(v).strip() for v in value if str(v).strip()]
            return ", ".join(cleaned)
        return str(value or "").strip()

    def _build_tablet_product_payload(self, product: Any, fallback: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        data = {}
        if isinstance(product, dict):
            data = dict(product)
        elif hasattr(product, "to_dict"):
            try:
                data = dict(product.to_dict())
            except Exception:
                data = {}

        fallback = fallback or {}
        ean = str(data.get("ean13") or data.get("ean") or fallback.get("ean") or "").strip()
        name = str(data.get("name") or fallback.get("name") or "Produit inconnu").strip()
        brand = str(data.get("brand") or fallback.get("brand") or "").strip()
        usage = str(data.get("usage") or data.get("instructions") or fallback.get("usage") or "").strip()
        image = str(data.get("photo_url") or data.get("image") or fallback.get("image") or "").strip()

        price_value = data.get("price", fallback.get("price", 0.0))
        try:
            price = float(price_value or 0.0)
        except Exception:
            price = 0.0

        return {
            "ean": ean,
            "name": name,
            "brand": brand,
            "price": price,
            "usage": usage,
            "hair_type": self._normalize_hair_type(data.get("hair_type", fallback.get("hair_type", ""))),
            "image": image,
        }

    def _to_tablet_product(self, payload: Dict[str, Any]):
        if not self._tablet_product_cls:
            class _ProductWrapper:
                def __init__(self, data: Dict[str, Any]):
                    self._data = dict(data)

                def to_dict(self) -> Dict[str, Any]:
                    return dict(self._data)

            return _ProductWrapper(payload)
        return self._tablet_product_cls(
            ean=payload.get("ean", ""),
            name=payload.get("name", ""),
            brand=payload.get("brand", ""),
            price=float(payload.get("price", 0.0) or 0.0),
            usage=payload.get("usage", ""),
            hair_type=payload.get("hair_type", ""),
            image=payload.get("image", ""),
        )

    def _to_tablet_top3_result(self, payload: Dict[str, Any]):
        if not self._tablet_top3_cls:
            return payload
        return self._tablet_top3_cls(
            ean=payload.get("ean", ""),
            name=payload.get("name", ""),
            confidence=float(payload.get("confidence", 0.0) or 0.0),
            image=payload.get("image", ""),
        )

    async def _capture_scan_images(self, num_frames: int, interval_s: float = 0.18) -> List[Any]:
        if not self.adapter or not hasattr(self.adapter, "capture_image"):
            return []

        captured: List[Any] = []
        frames = max(1, int(num_frames))

        for idx in range(frames):
            raw = await asyncio.to_thread(self.adapter.capture_image)
            image = self._extract_image_from_frame(raw)
            if image is not None:
                captured.append(image)
            if idx < frames - 1:
                await asyncio.sleep(max(0.05, float(interval_s)))

        return captured

    def _find_product_by_ean(self, ean: str):
        if not self.database or not hasattr(self.database, "get_by_ean"):
            return None
        try:
            return self.database.get_by_ean(ean)
        except Exception:
            return None

    def _find_product_by_id(self, product_id: str):
        if not self.database or not hasattr(self.database, "get_by_id"):
            return None
        try:
            return self.database.get_by_id(product_id)
        except Exception:
            return None

    def _fuzzy_find_product(self, query: str):
        if not query or not self.database or not hasattr(self.database, "search_fuzzy"):
            return None
        try:
            results = self.database.search_fuzzy(query, limit=1, min_score=0.35)
            if not results:
                return None
            first = results[0]
            return first.product if hasattr(first, "product") else first
        except Exception:
            return None

    async def _set_scan_led(self, color: Tuple[int, int, int]):
        # Met à jour les LEDs Pepper pour indiquer l'état du scan.
        if not self.adapter or not hasattr(self.adapter, "set_led_rgb"):
            return
        try:
            r, g, b = color
            await asyncio.to_thread(self.adapter.set_led_rgb, int(r), int(g), int(b), True)
        except Exception:
            pass

    async def _say_scan_status(self, text: str):
        # Message vocal court pour rendre le scan perceptible.
        if not text or not self.adapter or not hasattr(self.adapter, "say"):
            return
        try:
            await asyncio.to_thread(self.adapter.say, text, False)
        except Exception:
            pass

    async def _detect_barcode_from_images(self, images: List[Any]) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        # Détection code-barres directe (sans dépendre du VLM).
        detector = getattr(getattr(self.vision_pipeline, "pipeline", None), "barcode_detector", None)
        if not detector or not hasattr(detector, "detect_in_images"):
            return False, "", None

        try:
            barcode = await asyncio.to_thread(detector.detect_in_images, images)
        except Exception:
            barcode = None

        if not barcode or not getattr(barcode, "ean13", None):
            return False, "", None

        ean = str(barcode.ean13 or "").strip()
        product = self._find_product_by_ean(ean)
        payload = self._build_tablet_product_payload(product, fallback={"ean": ean})
        return True, ean, payload

    @staticmethod
    def _is_vlm_unavailable_message(message: str) -> bool:
        text = (message or "").lower()
        markers = (
            "chargement du modèle vlm échoué",
            "huggingface",
            "ssl",
            "handshake",
            "httpsconnectionpool",
        )
        return any(marker in text for marker in markers)

    async def _perform_visual_scan(self) -> Tuple[str, Any]:
        if not self.vision_pipeline:
            return "error", "Le module vision n'est pas disponible."

        images = await self._capture_scan_images(
            num_frames=max(3, int(getattr(self.config.vision, "num_frames", 3) or 3))
        )
        if not images:
            return "error", "Aucune image capturée. Vérifiez la caméra Pepper."

        try:
            result = await asyncio.to_thread(self.vision_pipeline.identify_product, images)
        except Exception as e:
            return "error", f"Erreur scan visuel: {e}"

        raw = getattr(result, "raw_result", None)
        if not result or not getattr(result, "success", False):
            message = getattr(result, "message", "") or "Le produit n'a pas pu être identifié."
            if self._is_vlm_unavailable_message(message):
                ok, _, payload = await self._detect_barcode_from_images(images)
                if ok and payload:
                    return "product", payload
                return "barcode", (
                    "Le modèle visuel n'est pas disponible actuellement. "
                    "Passez en scan code-barres."
                )
            return "error", message

        if raw and getattr(raw, "source", None) and getattr(raw.source, "value", "") == "vlm_medium":
            top3_payloads = []
            for pred in (getattr(result, "predictions", []) or [])[:3]:
                product = None
                pred_id = str(getattr(pred, "product_id", "") or "").strip()
                pred_name = str(getattr(pred, "name", "") or "").strip()
                if pred_id:
                    product = self._find_product_by_id(pred_id)
                if product is None and pred_name:
                    product = self._fuzzy_find_product(pred_name)
                payload = self._build_tablet_product_payload(
                    product,
                    fallback={
                        "name": pred_name,
                        "brand": str(getattr(pred, "brand", "") or "").strip(),
                        "image": "",
                    }
                )
                payload["confidence"] = float(getattr(pred, "confidence", 0.0) or 0.0)
                top3_payloads.append(payload)

            if top3_payloads:
                return "top3", top3_payloads

        ean = ""
        fallback_info: Dict[str, Any] = {}
        barcode_result = getattr(raw, "barcode_result", None) if raw else None
        if barcode_result and getattr(barcode_result, "ean13", None):
            ean = str(barcode_result.ean13 or "").strip()
            fallback_info["ean"] = ean

        top_prediction = getattr(result, "top_prediction", None)
        if top_prediction:
            fallback_info["name"] = str(getattr(top_prediction, "name", "") or "")
            fallback_info["brand"] = str(getattr(top_prediction, "brand", "") or "")

        product = self._find_product_by_ean(ean) if ean else None
        if product is None:
            pred_id = str(getattr(top_prediction, "product_id", "") or "").strip() if top_prediction else ""
            if pred_id:
                product = self._find_product_by_id(pred_id)
        if product is None and fallback_info.get("name"):
            product = self._fuzzy_find_product(fallback_info.get("name", ""))

        if product is None and not ean:
            message = getattr(result, "message", "") or "Produit non reconnu visuellement."
            return "barcode", message

        payload = self._build_tablet_product_payload(product, fallback=fallback_info)
        if not payload.get("name"):
            return "error", "Produit détecté mais introuvable en base."

        return "product", payload

    async def _perform_barcode_scan(self) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        if not self.vision_pipeline:
            return False, "", None

        attempts = 6

        for _ in range(attempts):
            images = await self._capture_scan_images(num_frames=2, interval_s=0.12)
            if not images:
                await asyncio.sleep(0.2)
                continue

            ok, ean, payload = await self._detect_barcode_from_images(images)
            if ok:
                return True, ean, payload

            await asyncio.sleep(0.2)

        return False, "", None

    async def _handle_tablet_start_visual_scan(self, websocket, data):
        # Lance un scan visuel piloté par la tablette.
        if self._scan_lock.locked():
            await self.tablet_server._send_error(websocket, "Scan déjà en cours.")
            return
        if not self.adapter or not hasattr(self.adapter, "capture_image"):
            await self.tablet_server._send_error(websocket, "Caméra Pepper indisponible.")
            return
        if not self.vision_pipeline:
            await self.tablet_server._send_error(websocket, "Module vision indisponible.")
            return

        async with self._scan_lock:
            try:
                if self.adapter and hasattr(self.adapter, "freeze_head"):
                    await asyncio.to_thread(self.adapter.freeze_head)
                await self._set_scan_led((140, 0, 255))
                await self._say_scan_status("Je scanne le produit.")

                await self.tablet_server.send_show_screen(websocket, "loading")
                mode, payload = await self._perform_visual_scan()

                if mode == "product":
                    await self._set_scan_led((0, 190, 0))
                    await self.tablet_server.send_product_identified(
                        websocket,
                        self._to_tablet_product(payload)
                    )
                elif mode == "top3":
                    await self._set_scan_led((255, 140, 0))
                    top3 = [self._to_tablet_top3_result(item) for item in payload]
                    await self.tablet_server.send_top3_results(websocket, top3)
                elif mode == "error":
                    await self._set_scan_led((220, 30, 30))
                    await self._say_scan_status("Le scan visuel a échoué.")
                    await self.tablet_server._send_error(websocket, str(payload))
                    await self.tablet_server.send_show_screen(websocket, "scan-choice")
                elif mode == "barcode":
                    await self._set_scan_led((255, 140, 0))
                    await self._say_scan_status("Je passe au scan du code barres.")
                    await self.tablet_server.send_show_screen(websocket, "barcode-scan")
                    if payload:
                        await self.tablet_server.send_security_alert(
                            websocket,
                            "Scan visuel insuffisant",
                            str(payload)
                        )
                else:
                    await self.tablet_server.send_show_screen(websocket, "barcode-scan")
            finally:
                if self.adapter and hasattr(self.adapter, "unfreeze_head"):
                    await asyncio.to_thread(self.adapter.unfreeze_head)
                await self._set_scan_led((255, 255, 255))

    async def _handle_tablet_start_barcode_scan(self, websocket, data):
        # Lance un scan code-barres dédié.
        if self._scan_lock.locked():
            await self.tablet_server._send_error(websocket, "Scan déjà en cours.")
            return
        if not self.adapter or not hasattr(self.adapter, "capture_image"):
            await self.tablet_server._send_error(websocket, "Caméra Pepper indisponible.")
            return
        if not self.vision_pipeline:
            await self.tablet_server._send_error(websocket, "Module vision indisponible.")
            return

        async with self._scan_lock:
            try:
                if self.adapter and hasattr(self.adapter, "freeze_head"):
                    await asyncio.to_thread(self.adapter.freeze_head)
                await self._set_scan_led((255, 140, 0))
                await self._say_scan_status("Je scanne le code barres.")
                await self.tablet_server.send_show_screen(websocket, "barcode-scan")

                ok, ean, payload = await self._perform_barcode_scan()
                if ok:
                    await self._set_scan_led((0, 190, 0))
                    product_msg = self._to_tablet_product(payload or {"ean": ean})
                    await self.tablet_server.send_barcode_detected(websocket, ean, product_msg)
                    if payload and payload.get("name"):
                        await self.tablet_server.send_product_identified(websocket, product_msg)
                    return

                await self._set_scan_led((220, 30, 30))
                await self._say_scan_status("Je n'ai pas détecté le code barres.")
                await self.tablet_server.send_barcode_failed(websocket)
            finally:
                if self.adapter and hasattr(self.adapter, "unfreeze_head"):
                    await asyncio.to_thread(self.adapter.unfreeze_head)
                await self._set_scan_led((255, 255, 255))

    async def _handle_tablet_confirm_product(self, websocket, data):
        # Confirmation d'un produit Top-3 côté tablette.
        ean = str((data or {}).get("ean") or "").strip()
        if not ean:
            await self.tablet_server._send_error(websocket, "EAN manquant pour la confirmation.")
            return

        product = self._find_product_by_ean(ean)
        if not product:
            await self.tablet_server._send_error(websocket, "Produit introuvable en base.")
            return

        payload = self._build_tablet_product_payload(product)
        await self.tablet_server.send_product_identified(
            websocket,
            self._to_tablet_product(payload)
        )

    async def _handle_tablet_start_voice_question(self, websocket, data):
        # Déclenche une fenêtre d'écoute vocale fallback via bouton tablette.
        if self._is_realtime_connected():
            await self.tablet_server.send_security_alert(
                websocket,
                "Mode vocal",
                "Realtime est déjà actif. Vous pouvez parler directement."
            )
            return

        if not self.voice_fallback:
            await self.tablet_server._send_error(
                websocket,
                "Fallback vocal indisponible (vérifier OpenAI et micro Pepper)."
            )
            return

        duration = 9.0
        try:
            requested = float((data or {}).get("duration_s", duration))
            duration = max(3.0, min(20.0, requested))
        except Exception:
            pass

        if hasattr(self.voice_fallback, "arm_listen_window"):
            await asyncio.to_thread(self.voice_fallback.arm_listen_window, duration)

        if self.adapter and hasattr(self.adapter, "say"):
            await asyncio.to_thread(self.adapter.say, "Je vous écoute.", False)

        await self.tablet_server.send_security_alert(
            websocket,
            "Question vocale",
            f"Parlez maintenant. Fenêtre d'écoute active pendant {int(duration)} secondes."
        )

    async def _handle_tablet_ask_question(self, websocket, data):
        # Désactivé: questions uniquement à l'oral.
        await self.tablet_server._send_error(
            websocket,
            "Question texte désactivée. Utilisez le bouton de question vocale."
        )

    def _get_loaded_modules(self) -> list:
        # Retourne la liste des modules charges.
        modules = []
        if self.adapter:
            modules.append(f"adapter:{type(self.adapter).__name__}")
        if self.database:
            modules.append("database")
        if self.security_module:
            modules.append("security")
        if self.vision_pipeline:
            modules.append("vision")
        if self.openai_client:
            modules.append("openai")
        if self.http_fallback_client:
            modules.append("openai_http_fallback")
        if self.voice_fallback:
            modules.append("voice_http_fallback")
        if self.tablet_server:
            modules.append("tablet")
        if self.orchestrator:
            modules.append("orchestrator")
        return modules

    async def run(self):
        # Lance le systeme complet.
        self._running = True
        self._main_loop = asyncio.get_running_loop()
        session_id = self.logger.start_session()

        self.logger.log_info("=" * 50)
        self.logger.log_info("ASSISTANT PARAPHARMACIE PEPPER")
        self.logger.log_info(f"   Mode: {self.config.mode.value}")
        self.logger.log_info(f"   Session: {session_id}")
        self.logger.log_info("=" * 50)

        try:
            # Demarrer les taches paralleles
            self._tasks = []

            # Serveur tablette
            if self.tablet_server:
                self._tasks.append(asyncio.create_task(
                    self._run_tablet_server(),
                    name="tablet_server"
                ))

            # Orchestrateur
            if self.orchestrator:
                self._tasks.append(asyncio.create_task(
                    self._run_orchestrator(),
                    name="orchestrator"
                ))

            # Client OpenAI
            if self.openai_client:
                self._tasks.append(asyncio.create_task(
                    self._run_openai_client(),
                    name="openai_client"
                ))

            # Afficher la tablette Pepper automatiquement.
            self._tasks.append(asyncio.create_task(
                self._auto_show_tablet(),
                name="auto_show_tablet"
            ))

            self.logger.log_info(f"Demarrage de {len(self._tasks)} taches paralleles")

            # Attendre l'arret
            await self._shutdown_event.wait()

        except asyncio.CancelledError:
            self.logger.log_info("Arret demande")
        except Exception as e:
            self.logger.log_critical("Erreur critique", exception=e)
        finally:
            await self.shutdown()

    async def _run_tablet_server(self):
        # Lance le serveur tablette.
        try:
            self.logger.log_event(LogEvent.TABLET_CONNECTED, {"status": "starting"})
            await self.tablet_server.start()
        except Exception as e:
            self.logger.log_error("Erreur serveur tablette", exception=e)

    async def _run_orchestrator(self):
        # Lance l'orchestrateur.
        try:
            await self.orchestrator.run()
        except Exception as e:
            self.logger.log_error("Erreur orchestrateur", exception=e)

    async def _run_openai_client(self):
        # Lance le client OpenAI.
        try:
            if self.openai_client.connect():
                self.logger.log_info("Client OpenAI connecte")
                # Boucle de maintien connexion
                while self._running:
                    await asyncio.sleep(1)
            else:
                self.logger.log_warning("Client OpenAI Realtime indisponible")
                if self.voice_fallback:
                    self.logger.log_warning(
                        "Fallback vocal HTTP actif (micro Pepper + transcription HTTP)"
                    )
                elif self.http_fallback_client:
                    self.logger.log_warning(
                        "Fallback HTTP texte disponible mais désactivé côté tablette"
                    )
        except Exception as e:
            self.logger.log_error("Erreur client OpenAI", exception=e)

    def _resolve_local_ip_for_pepper(self) -> str:
        # Déduit l'IP locale utile pour joindre Pepper.
        pepper_ip = (self.config.pepper.ip or "").strip()
        if not pepper_ip:
            return "127.0.0.1"
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.connect((pepper_ip, int(self.config.pepper.port or 9559)))
            local_ip = sock.getsockname()[0]
            sock.close()
            if local_ip:
                return local_ip
        except Exception:
            pass
        return "127.0.0.1"

    def _resolve_tablet_url(self) -> str:
        # URL tablette à afficher sur Pepper.
        env_url = (os.getenv("PEPPER_TABLET_URL", "") or os.getenv("TABLET_URL", "")).strip()
        if self._tablet_url_override:
            return self._tablet_url_override
        if env_url:
            return env_url
        local_ip = self._resolve_local_ip_for_pepper()
        return f"http://{local_ip}:8080/index.html"

    @staticmethod
    def _with_cache_buster(url: str) -> str:
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}cb={int(time.time())}"

    async def _auto_show_tablet(self):
        # Tente d'afficher la webview tablette sur Pepper.
        if not self.adapter or not hasattr(self.adapter, "show_on_tablet"):
            return
        if self.config.mode == RunMode.SIMULATION:
            return

        url = self._resolve_tablet_url()
        ws_host = self.config.tablet.ws_host
        ws_port = self.config.tablet.ws_port
        if ws_host in ("0.0.0.0", "", None):
            ws_host = self._resolve_local_ip_for_pepper()
        self.logger.log_info(f"  URL tablette Pepper: {url}")
        self.logger.log_info(f"  WS tablette attendu: ws://{ws_host}:{ws_port}")

        # Vérifier localement que le serveur HTTP tablette est bien lancé.
        try:
            await asyncio.to_thread(urllib.request.urlopen, url, None, 1.5)
        except Exception:
            self.logger.log_warning(
                "  Tablette HTTP non joignable localement. "
                "Lance: cd tablet && python3 -m http.server 8080 --bind 0.0.0.0"
            )

        # Affichage Pepper avec retries courts.
        for attempt in range(1, 4):
            try:
                target_url = self._with_cache_buster(url)
                ok = await asyncio.to_thread(self.adapter.show_on_tablet, target_url)
                if ok:
                    self.logger.log_info(f"  Tablette Pepper affichee (tentative {attempt})")
                    return
            except Exception:
                pass
            await asyncio.sleep(1.0)

        self.logger.log_warning(
            "  Impossible d'afficher la tablette sur Pepper automatiquement."
        )

    async def shutdown(self):
        # Arrete proprement le systeme.
        if not self._running:
            return

        self._running = False
        self.logger.log_info("Arret du systeme...")

        # Annuler toutes les taches
        for task in self._tasks:
            if not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=5.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass

        # Arreter les modules
        if self.orchestrator:
            try:
                await self.orchestrator.stop()
            except:
                pass

        if self.tablet_server:
            try:
                await self.tablet_server.stop()
            except:
                pass

        if self.openai_client:
            try:
                self.openai_client.disconnect()
            except:
                pass

        if self.voice_fallback:
            try:
                self.voice_fallback.stop()
            except:
                pass
            self.voice_fallback = None

        if self.adapter:
            try:
                self.adapter.disconnect()
            except:
                pass

        # Fermer la base de donnees
        if self.database:
            try:
                self.database.close()
            except:
                pass

        # Finaliser le logging
        stats = self.logger.get_stats()
        self.logger.end_session(stats)

        self.logger.log_event(LogEvent.SYSTEM_STOP, {
            "stats": stats
        })

        self.logger.log_info("Systeme arrete proprement")
        self._main_loop = None
        self.logger.close()

    def request_shutdown(self):
        # Demande l'arret du systeme.
        self._shutdown_event.set()



def setup_signal_handlers(assistant: PepperAssistant):
    # Configure les handlers de signaux.
    def signal_handler(sig, frame):
        # Gere handler.
        print("\nSignal d'arret recu, arret en cours...")
        assistant.request_shutdown()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


def parse_args():
    # Parse les arguments de ligne de commande.
    parser = argparse.ArgumentParser(
        description="Assistant Parapharmacie Pepper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  python -m assistant.main                    # Mode developpement
  python -m assistant.main --simulation       # Mode simulation (sans robot)
  python -m assistant.main --production       # Mode production
  python -m assistant.main --pepper-ip 192.168.1.100  # Connexion a Pepper
        """
    )

    parser.add_argument("--production", action="store_true",
                        help="Mode production")
    parser.add_argument("--simulation", action="store_true",
                        help="Mode simulation (sans materiel)")
    parser.add_argument("--test", action="store_true",
                        help="Mode test (timeouts courts)")
    parser.add_argument("--pepper-ip", type=str, default="",
                        help="Adresse IP du robot Pepper")
    parser.add_argument("--tablet-url", type=str, default="",
                        help="URL web a afficher sur la tablette Pepper (optionnel)")
    parser.add_argument("--config", type=str,
                        help="Fichier de configuration YAML/JSON")
    parser.add_argument("--debug", action="store_true",
                        help="Activer le mode debug")

    return parser.parse_args()


async def main():
    # Point d'entree principal.
    args = parse_args()
    default_config_path = Path(__file__).resolve().parents[2] / "config" / "config.yaml"

    # Determiner la configuration
    if args.config:
        config = Config.load(args.config)
    elif args.production:
        config = get_production_config()
    elif args.simulation:
        config = get_simulation_config()
    elif args.test:
        from assistant.config import get_test_config
        config = get_test_config()
    elif default_config_path.exists():
        config = Config.load(str(default_config_path))
    else:
        config = get_development_config()

    # Override IP Pepper si fournie
    if args.pepper_ip:
        config.pepper.ip = args.pepper_ip

    # Mode debug
    if args.debug:
        config.logging.console_level = "DEBUG"
        config.logging.file_level = "DEBUG"

    # Creer et demarrer l'assistant
    assistant = PepperAssistant(config, tablet_url_override=args.tablet_url)

    # Configurer les handlers de signaux
    setup_signal_handlers(assistant)

    # Initialiser et lancer
    await assistant.setup()
    await assistant.run()


def run():
    # Point d'entree pour le script console.
    asyncio.run(main())


if __name__ == "__main__":
    run()
