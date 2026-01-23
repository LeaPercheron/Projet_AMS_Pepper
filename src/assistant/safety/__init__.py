"""
Module Securite
===============
Filtres de securite pour detecter les requetes medicales inappropriees.

Usage:
    from assistant.safety import SecurityModule, SecurityConfig, SecurityAlert

    security = SecurityModule()
    alert = security.check_text("puis-je boire ce shampooing?")
    if alert.triggered:
        print(alert.response)
"""

from .security_module import (
    SecurityModule,
    SecurityConfig,
    SecurityAlert,
    AlertType,
    AlertSeverity,
    RobotSecurityActions,
)

__all__ = [
    "SecurityModule",
    "SecurityConfig",
    "SecurityAlert",
    "AlertType",
    "AlertSeverity",
    "RobotSecurityActions",
]
