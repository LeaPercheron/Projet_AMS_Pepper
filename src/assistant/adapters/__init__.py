"""
Module Adaptateurs Hardware
===========================
Abstractions pour le robot Pepper et mode simulation.

Usage:
    from assistant.adapters import get_adapter, PepperAdapter, MockAdapter

    # Automatique selon configuration
    adapter = get_adapter(config)

    # Ou explicite
    pepper = PepperAdapter(ip="192.168.1.100")
    mock = MockAdapter()
"""

from .base import RobotAdapter, AdapterConfig
from .pepper_adapter import PepperAdapter
from .mock_adapter import MockAdapter


def get_adapter(config=None) -> RobotAdapter:
    """
    Retourne l'adaptateur approprie selon la configuration.

    Args:
        config: Configuration (optionnel)

    Returns:
        PepperAdapter si IP configuree, MockAdapter sinon
    """
    if config and hasattr(config, 'pepper') and config.pepper.ip:
        return PepperAdapter(
            ip=config.pepper.ip,
            port=config.pepper.port
        )
    return MockAdapter()


__all__ = [
    "RobotAdapter",
    "AdapterConfig",
    "PepperAdapter",
    "MockAdapter",
    "get_adapter",
]
