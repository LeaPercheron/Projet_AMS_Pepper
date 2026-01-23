"""
Module Audio
============
Capture, traitement et gestion audio pour l'assistant.

Composants:
- capture: Capture audio depuis Pepper ou microphone local
- processing: Traitement audio (beamforming, reduction bruit, AGC)
- half_duplex: Gestion half-duplex pour eviter les boucles audio
- vad_config: Configuration Voice Activity Detection
- prompt_system: Systeme de prompts pour le dialogue

Usage:
    from assistant.audio import AudioProcessor, HalfDuplexManager
    from assistant.audio.vad_config import get_vad_preset
"""

from .processing import (
    AudioProcessor,
    AudioConfig,
    Beamformer,
    NoiseReducer,
    AutomaticGainControl,
    SoftLimiter,
    HighPassFilter,
    Resampler,
    BeamformingMode,
    get_preset_config
)

from .half_duplex import (
    HalfDuplexManager,
    HalfDuplexConfig,
    SpeakingState,
    RealtimeHalfDuplexAdapter
)

__all__ = [
    # Processing
    "AudioProcessor",
    "AudioConfig",
    "Beamformer",
    "NoiseReducer",
    "AutomaticGainControl",
    "SoftLimiter",
    "HighPassFilter",
    "Resampler",
    "BeamformingMode",
    "get_preset_config",
    # Half-duplex
    "HalfDuplexManager",
    "HalfDuplexConfig",
    "SpeakingState",
    "RealtimeHalfDuplexAdapter",
]
