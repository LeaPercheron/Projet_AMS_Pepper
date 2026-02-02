# Module Adaptateurs Hardware

from .base import RobotAdapter, AdapterConfig
from .pepper_adapter import PepperAdapter
from .mock_adapter import MockAdapter


def get_adapter(config=None) -> RobotAdapter:
    # Retourne l'adaptateur approprie selon la configuration.
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
