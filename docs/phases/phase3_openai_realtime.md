# Phase 3 - OpenAI Realtime API

## Objectif

Integrer l'API OpenAI Realtime pour conversation vocale bidirectionnelle en temps reel.

## Architecture

```
Mac (24kHz mono) → WebSocket → OpenAI Realtime → GPT-4o → WebSocket → Mac → Pepper (48kHz stereo)
```

## Specifications API

- **URL**: `wss://api.openai.com/v1/realtime`
- **Modele**: `gpt-4o-realtime-preview-2024-10-01`
- **Format audio**: PCM16 24kHz mono
- **Encodage**: Base64

## Fonctionnalites

### Voice Activity Detection (VAD)
Detection de parole cote serveur:
- **Threshold**: 0.5 (sensibilite)
- **Prefix padding**: 300ms (avant parole)
- **Silence duration**: 500ms (fin de phrase)

### Voix Disponibles
- alloy, echo, fable, onyx, nova, shimmer

### Streaming Bidirectionnel
- Envoi audio en chunks de 100ms
- Reception audio + transcription en temps reel
- Latence TTFB cible: < 1000ms

## Evenements

### Envoi (Client → API)
- `session.update`: Configuration session
- `input_audio_buffer.append`: Envoi audio
- `input_audio_buffer.commit`: Fin de parole
- `response.cancel`: Annuler reponse

### Reception (API → Client)
- `session.created`: Session etablie
- `response.audio.delta`: Audio en streaming
- `response.audio_transcript.delta`: Transcription
- `input_audio_buffer.speech_started`: Debut parole
- `input_audio_buffer.speech_stopped`: Fin parole

## Instructions Systeme

Le client est pre-configure avec des instructions specifiques parapharmacie:
- Repond uniquement sur les produits capillaires
- Ne donne jamais de conseil medical
- Redirige vers pharmacien si necessaire
- Reponses concises (2-3 phrases)

## Integration dans la Nouvelle Structure

**Emplacement**: `src/assistant/realtime/client.py`

**Usage**:
```python
from assistant.realtime import OpenAIRealtimeClient, create_parapharmacie_client

# Client pre-configure
client = create_parapharmacie_client()

# Callbacks
client.on('on_audio_received', handle_audio)
client.on('on_transcript', handle_text)

# Connexion et envoi
client.connect()
client.send_audio(audio_bytes)
```

**Configuration**:
```python
from assistant.realtime import RealtimeConfig

config = RealtimeConfig(
    voice="shimmer",
    turn_detection_threshold=0.5,
    turn_detection_silence_duration_ms=700
)
```
