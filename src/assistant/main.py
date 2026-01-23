#!/usr/bin/env python3
"""
Point d'Entree Principal - Parapharma Assistant
================================================
Lance l'assistant vocal parapharmacie pour robot Pepper.

Usage:
    # Mode simulation (sans robot)
    python -m assistant.main --simulation

    # Mode avec Pepper
    python -m assistant.main --pepper-ip 192.168.1.100

    # Mode production
    python -m assistant.main --production

    # Afficher l'aide
    python -m assistant.main --help
"""

import asyncio
import argparse
import signal
import sys
import os
from pathlib import Path
from typing import Optional

# Ajouter le repertoire src au path
src_path = Path(__file__).parent.parent
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from assistant.config import (
    Config, RunMode, get_config, reset_config,
    get_development_config, get_production_config, get_simulation_config
)
from assistant.logger import SystemLogger, LogEvent, get_logger


class PepperAssistant:
    """
    Assistant Parapharmacie Robotique - Systeme Integre.

    Coordonne tous les modules:
    - adapters: Communication avec Pepper (ou simulation)
    - audio: Capture et traitement audio
    - realtime: Client OpenAI Realtime API
    - vision: Identification produits (VLM + code-barres)
    - database: Base de donnees produits
    - safety: Filtres de securite
    - orchestrator: Machine a etats
    """

    def __init__(self, config: Config):
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
        self.vision_pipeline = None
        self.database = None
        self.security_module = None
        self.tablet_server = None

        # Etat
        self._running = False
        self._tasks = []
        self._shutdown_event = asyncio.Event()

    async def setup(self):
        """Initialise tous les modules."""
        self.logger.log_event(LogEvent.SYSTEM_START, {
            "mode": self.config.mode.value,
            "production": self.config.PRODUCTION_MODE
        })

        self.logger.log_info(f"Initialisation en mode {self.config.mode.value}...")

        # ==================== ADAPTATEUR ROBOT ====================
        await self._setup_adapter()

        # ==================== BASE DE DONNEES ====================
        await self._setup_database()

        # ==================== SECURITE ====================
        await self._setup_security()

        # ==================== VISION ====================
        await self._setup_vision()

        # ==================== AUDIO / OPENAI ====================
        await self._setup_audio()

        # ==================== TABLETTE ====================
        await self._setup_tablet()

        # ==================== ORCHESTRATEUR ====================
        await self._setup_orchestrator()

        self.logger.log_event(LogEvent.CONFIG_LOADED, {
            "modules_loaded": self._get_loaded_modules()
        })

        self.logger.log_info("Tous les modules initialises")

    async def _setup_adapter(self):
        """Configure l'adaptateur robot."""
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
        """Configure le module base de donnees."""
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
        """Configure le module securite."""
        self.logger.log_info("Chargement module securite...")

        try:
            from assistant.safety import SecurityModule, SecurityConfig as SecConfig

            # SecurityConfig utilise les valeurs par defaut
            self.security_module = SecurityModule(SecConfig())

            self.logger.log_info("  Module securite: OK")

        except ImportError as e:
            self.logger.log_warning(f"Module securite non disponible: {e}")
        except Exception as e:
            self.logger.log_error("Erreur chargement securite", exception=e)

    async def _setup_vision(self):
        """Configure le module vision."""
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

            self.vision_pipeline = VisionModule(vision_config)
            self.logger.log_info(f"  Vision: {self.config.vision.vlm_model}")

        except ImportError as e:
            self.logger.log_warning(f"Module vision non disponible: {e}")
        except Exception as e:
            self.logger.log_error("Erreur chargement vision", exception=e)

    async def _setup_audio(self):
        """Configure les modules audio (OpenAI + VAD)."""
        if self.config.mode == RunMode.SIMULATION:
            self.logger.log_info("Audio: mode simulation")
            return

        self.logger.log_info("Chargement module audio...")

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
            else:
                self.logger.log_warning("  OpenAI: Pas de cle API configuree")

        except ImportError as e:
            self.logger.log_warning(f"Module OpenAI non disponible: {e}")
        except Exception as e:
            self.logger.log_error("Erreur chargement audio", exception=e)

    async def _setup_tablet(self):
        """Configure le serveur tablette."""
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
        """Configure l'orchestrateur."""
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

            self.logger.log_info("  Orchestrateur: OK")

        except ImportError as e:
            self.logger.log_warning(f"Module orchestrateur non disponible: {e}")
        except Exception as e:
            self.logger.log_error("Erreur chargement orchestrateur", exception=e)

    def _get_loaded_modules(self) -> list:
        """Retourne la liste des modules charges."""
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
        if self.tablet_server:
            modules.append("tablet")
        if self.orchestrator:
            modules.append("orchestrator")
        return modules

    async def run(self):
        """Lance le systeme complet."""
        self._running = True
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
        """Lance le serveur tablette."""
        try:
            self.logger.log_event(LogEvent.TABLET_CONNECTED, {"status": "starting"})
            await self.tablet_server.start()
        except Exception as e:
            self.logger.log_error("Erreur serveur tablette", exception=e)

    async def _run_orchestrator(self):
        """Lance l'orchestrateur."""
        try:
            await self.orchestrator.run()
        except Exception as e:
            self.logger.log_error("Erreur orchestrateur", exception=e)

    async def _run_openai_client(self):
        """Lance le client OpenAI."""
        try:
            if self.openai_client.connect():
                self.logger.log_info("Client OpenAI connecte")
                # Boucle de maintien connexion
                while self._running:
                    await asyncio.sleep(1)
        except Exception as e:
            self.logger.log_error("Erreur client OpenAI", exception=e)

    async def shutdown(self):
        """Arrete proprement le systeme."""
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
        self.logger.close()

    def request_shutdown(self):
        """Demande l'arret du systeme."""
        self._shutdown_event.set()


# ==================== POINT D'ENTREE ====================

def setup_signal_handlers(assistant: PepperAssistant):
    """Configure les handlers de signaux."""
    def signal_handler(sig, frame):
        print("\nSignal d'arret recu, arret en cours...")
        assistant.request_shutdown()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


def parse_args():
    """Parse les arguments de ligne de commande."""
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
    parser.add_argument("--config", type=str,
                        help="Fichier de configuration YAML/JSON")
    parser.add_argument("--debug", action="store_true",
                        help="Activer le mode debug")

    return parser.parse_args()


async def main():
    """Point d'entree principal."""
    args = parse_args()

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
    assistant = PepperAssistant(config)

    # Configurer les handlers de signaux
    setup_signal_handlers(assistant)

    # Initialiser et lancer
    await assistant.setup()
    await assistant.run()


def run():
    """Point d'entree pour le script console."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
