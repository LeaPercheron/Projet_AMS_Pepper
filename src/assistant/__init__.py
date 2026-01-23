"""
Parapharma Assistant - Assistant vocal parapharmacie pour robot Pepper
======================================================================

Ce package contient tous les modules de l'assistant parapharmacie:
- adapters: Adaptateurs hardware (Pepper, Mock)
- audio: Capture, traitement et VAD
- realtime: Client OpenAI Realtime API
- vision: VLM et detection code-barres
- database: Base de donnees produits
- safety: Filtres de securite
- orchestrator: Machine a etats

Usage:
    from assistant.main import PepperAssistant
    from assistant.config import get_config, RunMode
"""

__version__ = "1.0.0"
__author__ = "Projet AMS - Master 2"

from .config import Config, RunMode, get_config
from .logger import SystemLogger, get_logger

__all__ = [
    "Config",
    "RunMode",
    "get_config",
    "SystemLogger",
    "get_logger",
    "__version__",
]
