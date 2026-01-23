"""
Module OpenAI Realtime
======================
Client WebSocket pour l'API OpenAI Realtime.

Usage:
    from assistant.realtime import OpenAIRealtimeClient, RealtimeConfig
    from assistant.realtime import create_parapharmacie_client

    # Client personnalise
    client = OpenAIRealtimeClient(config)
    client.connect()
    client.send_audio(audio_bytes)

    # Client pre-configure parapharmacie
    client = create_parapharmacie_client()
"""

from .client import (
    OpenAIRealtimeClient,
    RealtimeConfig,
    AudioConverter,
    ConnectionState,
    ConversationState,
    LatencyMetrics,
    create_parapharmacie_client,
    PARAPHARMACIE_INSTRUCTIONS,
    OPENAI_SAMPLE_RATE,
    OPENAI_CHANNELS,
)

__all__ = [
    "OpenAIRealtimeClient",
    "RealtimeConfig",
    "AudioConverter",
    "ConnectionState",
    "ConversationState",
    "LatencyMetrics",
    "create_parapharmacie_client",
    "PARAPHARMACIE_INSTRUCTIONS",
    "OPENAI_SAMPLE_RATE",
    "OPENAI_CHANNELS",
]
