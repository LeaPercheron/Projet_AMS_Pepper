# Architecture Systeme

## Vue d'Ensemble

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           ROBOT PEPPER                                  │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐            │
│  │ 4 Mics       │     │ Camera       │     │ Speakers     │            │
│  │ (48kHz)      │     │ (VGA)        │     │ (Stereo)     │            │
│  └──────┬───────┘     └──────┬───────┘     └──────┬───────┘            │
└─────────┼─────────────────────┼─────────────────────┼──────────────────┘
          │                     │                     │
    TCP:5555            TCP (video)             TCP:5556
          │                     │                     │
          └─────────────────────┼─────────────────────┘
                                │
                  ┌─────────────▼─────────────┐
                  │       MAC M4 PRO          │
                  │                           │
        ┌─────────▼─────────┐    ┌───────────▼──────────┐
        │ Audio Processing  │    │ Vision Module        │
        │ • Beamforming     │    │ • VLM (Qwen2-VL)     │
        │ • Noise reduction │    │ • Barcode (pyzbar)   │
        │ • AGC             │    │                      │
        │ • Resample 24kHz  │    │                      │
        └────────┬──────────┘    └────────┬─────────────┘
                 │                        │
        ┌────────▼────────────────────────▼──────────┐
        │ OpenAI Realtime API (WebSocket)            │
        │ • GPT-4o-realtime                          │
        │ • VAD detection                            │
        │ • Streaming audio + transcription          │
        └────────┬──────────────────────────┬────────┘
                 │                          │
        ┌────────▼────────┐       ┌────────▼────────┐
        │ Safety Module   │       │ Database        │
        │ • Keywords      │       │ • SQLite        │
        │ • EAN blacklist │       │ • 30+ products  │
        └────────┬────────┘       └────────┬────────┘
                 │                          │
        ┌────────▼──────────────────────────▼────────┐
        │            Orchestrator                    │
        │        (State Machine - 11 etats)          │
        └────────┬──────────────────────────┬────────┘
                 │                          │
        ┌────────▼────────┐       ┌────────▼────────┐
        │ Tablet UI       │       │ LED Control     │
        │ • WebSocket     │       │ • Per-state     │
        │ • 7 screens     │       │ • Fade effect   │
        └─────────────────┘       └─────────────────┘
```

## Modules

### adapters/
Interface hardware avec abstraction Pepper/Mock.
- `base.py`: Interface abstraite RobotAdapter
- `pepper_adapter.py`: Implementation Pepper (NAOqi)
- `mock_adapter.py`: Simulation pour tests

### audio/
Pipeline de traitement audio.
- `processing.py`: Beamforming, AGC, reduction bruit
- `half_duplex.py`: Gestion anti-feedback
- `vad_config.py`: Presets VAD
- `capture.py`: Capture depuis Pepper

### realtime/
Client OpenAI Realtime API.
- `client.py`: WebSocket bidirectionnel
- Streaming audio/transcription
- Instructions parapharmacie

### vision/
Identification produits.
- `vision_module.py`: VLM + detection code-barres
- Seuils de confiance configurable
- Top-3 avec arbitrage

### database/
Gestion produits capillaires.
- `database_module.py`: CRUD SQLite
- 30+ produits, 100+ blacklist
- Recherche fuzzy

### safety/
Filtres de securite.
- `security_module.py`: Detection termes medicaux
- Blacklist EAN medicaments
- Reponses pre-generees

### orchestrator/
Machine a etats centrale.
- `orchestrator.py`: 11 etats, 20+ evenements
- Coordination tous modules
- Gestion timeouts

## Flux de Donnees

### Conversation Client

```
1. Client detecte → GREETING
2. Intent reconnu → AWAITING_INTENT
3. Produit montre → SCANNING_PRODUCT
4. VLM analyse → CONFIRMING_TOP3 ou DISPLAYING_INFO
5. Questions → CONVERSING (avec securite)
6. Fin → ENDING → IDLE
```

### Traitement Audio

```
Pepper 4ch 48kHz → TCP → Beamforming → Noise → AGC → 24kHz → OpenAI
OpenAI → 24kHz mono → 48kHz stereo → TCP → Pepper speakers
```

### Identification Produit

```
Camera → 3 frames → VLM classification → VLM identification
                 → Barcode detection
Decision: High (>85%) → Direct | Medium (60-85%) → Top-3 | Low → Fallback
```

## Technologies

| Composant | Technologie |
|-----------|-------------|
| Robot | Pepper (NAOqi SDK) |
| Traitement | Mac M4 Pro |
| VLM | mlx-vlm (Qwen2-VL-2B-4bit) |
| Audio | NumPy, SciPy |
| API vocale | OpenAI Realtime |
| Base donnees | SQLite |
| UI tablette | HTML/JS + WebSocket |
| Orchestration | Python asyncio |
