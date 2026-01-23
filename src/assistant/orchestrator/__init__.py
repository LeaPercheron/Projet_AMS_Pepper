"""
Module Orchestrateur
====================
Machine a etats gerant le flux de conversation complet.

Usage:
    from assistant.orchestrator import Orchestrator, OrchestratorConfig
    from assistant.orchestrator import State, Event

    orchestrator = Orchestrator(config)
    orchestrator.inject_modules(database, security, vision, tablet)
    await orchestrator.run()
"""

from .orchestrator import (
    Orchestrator,
    OrchestratorConfig,
    State,
    Event,
)

__all__ = [
    "Orchestrator",
    "OrchestratorConfig",
    "State",
    "Event",
]
