# Phase 1 - Pipeline Audio Bidirectionnel

## Objectif

Etablir la communication audio bidirectionnelle entre le robot Pepper et le Mac de traitement via TCP/IP.

## Architecture

```
Pepper Robot                         Mac M4 Pro
┌──────────────┐                    ┌──────────────┐
│ 4 Mics       │ ──TCP:5555──────→  │ Receiver     │
│ 48kHz 16-bit │                    │ Processing   │
└──────────────┘                    └──────────────┘

┌──────────────┐                    ┌──────────────┐
│ Speakers     │ ←──TCP:5556──────  │ Sender       │
│ 48kHz Stereo │                    │              │
└──────────────┘                    └──────────────┘
```

## Specifications Audio

### Capture (Pepper → Mac)
- **Canaux**: 4 (Front, Rear, Left, Right)
- **Frequence**: 48,000 Hz
- **Format**: PCM 16-bit signed, interleaved
- **Buffer**: 1024 samples/canal (~21ms)
- **Port TCP**: 5555

### Playback (Mac → Pepper)
- **Canaux**: 2 (Stereo)
- **Frequence**: 48,000 Hz
- **Format**: PCM 16-bit signed, interleaved
- **Port TCP**: 5556

## Protocole TCP

### Handshake Initial
```
MAGIC(4) + VERSION(1) + SAMPLE_RATE(4) + CHANNELS(1) + SAMPLE_WIDTH(1)
= "PAUC" + 0x01 + 48000 + 4 + 2
```

### Paquet Audio
```
SIZE(4) + TIMESTAMP_SEC(4) + TIMESTAMP_USEC(4) + DATA(N)
```

## Latence Cible

| Segment | Cible | Mesure |
|---------|-------|--------|
| Capture Pepper | < 50ms | ~21ms |
| Reseau | < 10ms | ~2ms |
| Traitement | < 50ms | Variable |
| Playback | < 50ms | ~21ms |
| **Total** | < 200ms | ~100ms |

## Integration dans la Nouvelle Structure

**Emplacement**: `src/assistant/audio/capture.py`

**Module**: Le code de capture est integre dans l'adaptateur Pepper (`src/assistant/adapters/pepper_adapter.py`)

**Usage**:
```python
from assistant.adapters import PepperAdapter

adapter = PepperAdapter(ip="192.168.1.100")
adapter.connect()
adapter.start_audio_capture(callback=on_audio_received)
```
