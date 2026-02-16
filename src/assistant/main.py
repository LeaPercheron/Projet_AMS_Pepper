#!/usr/bin/env python3
# Point d'Entree Principal - Parapharma Assistant

import asyncio
import argparse
import signal
import sys
import os
import socket
import urllib.request
from pathlib import Path
from typing import Optional

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

        # Etat
        self._running = False
        self._tasks = []
        self._shutdown_event = asyncio.Event()
        self._main_loop = None
        self._tablet_url_override = (tablet_url_override or "").strip()

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
                from server import TabletServer, ServerConfig as TabletServerConfig

                server_config = TabletServerConfig(
                    host=self.config.tablet.ws_host,
                    port=self.config.tablet.ws_port
                )
                self.tablet_server = TabletServer(config=server_config)

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
                transcription_model=transcription_model
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
        # Branche les commandes tablette custom (fallback Q/R).
        if not self.tablet_server:
            return
        try:
            self.tablet_server.register_handler("ask_question", self._handle_tablet_ask_question)
            self.logger.log_info("  Tablette: handler ask_question actif")
        except Exception as e:
            self.logger.log_warning(f"  Tablette: handler ask_question indisponible ({e})")

    def _is_realtime_connected(self) -> bool:
        return bool(self.openai_client and self.openai_client.is_connected())

    async def _handle_tablet_ask_question(self, websocket, data):
        # Fallback Q/R: question texte tablette -> OpenAI HTTP -> TTS Pepper.
        question = ((data or {}).get("question") or "").strip()
        if not question:
            await self.tablet_server._send_error(websocket, "Question vide.")
            return

        # Fallback actif uniquement si Realtime est indisponible.
        if self._is_realtime_connected():
            await self.tablet_server._send_error(
                websocket,
                "Realtime actif: utilisez la conversation vocale."
            )
            return

        if not self.http_fallback_client:
            await self.tablet_server._send_error(
                websocket,
                "Fallback HTTP indisponible (clé API ou dépendance manquante)."
            )
            return

        try:
            context = self.orchestrator.get_context() if self.orchestrator else {}

            if self.orchestrator:
                try:
                    from assistant.orchestrator import Event
                    await self.orchestrator.send_event(
                        Event.QUESTION_ASKED,
                        {"text": question, "source": "tablet"}
                    )
                except Exception:
                    pass

            answer = await asyncio.to_thread(self.http_fallback_client.ask, question, context)

            if self.adapter and hasattr(self.adapter, "say"):
                await asyncio.to_thread(self.adapter.say, answer, False)

            if hasattr(self.tablet_server, "send_qa_answer"):
                await self.tablet_server.send_qa_answer(websocket, question, answer)
            else:
                await self.tablet_server.send_security_alert(websocket, "Réponse Pepper", answer)

            if self.orchestrator:
                try:
                    from assistant.orchestrator import Event
                    await self.orchestrator.send_event(
                        Event.SPEECH_ENDED,
                        {"source": "http_fallback"}
                    )
                except Exception:
                    pass

        except Exception as e:
            self.logger.log_error("Erreur fallback HTTP question", exception=e)
            await self.tablet_server._send_error(
                websocket,
                "Erreur fallback HTTP lors du traitement de la question."
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
                        "Fallback HTTP actif via tablette (commande ask_question)"
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
                ok = await asyncio.to_thread(self.adapter.show_on_tablet, url)
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
