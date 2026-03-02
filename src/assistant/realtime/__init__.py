# Module OpenAI Realtime

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
