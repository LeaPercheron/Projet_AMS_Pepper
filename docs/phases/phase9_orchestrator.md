# Phase 9 - Orchestrateur (Machine a Etats)

## Objectif

Coordonner tous les modules via une machine a etats asynchrone gerant le flux complet de conversation.

## Diagramme d'Etats

```
IDLE ←─────────────────────────────────────────→ GREETING
       ↓                                          ↓
  AWAITING_INTENT ← ─ ─ ─ ─ ─ ─ ─ → SCANNING_PRODUCT
       ↓                                ↓        ↓
  CONVERSING          CONFIRMING_TOP3  SCANNING_BARCODE
       ↓                    ↓               ↓
  ADVISING ───────→ DISPLAYING_INFO ←──────┘
       ↓                    ↓
  AWAITING_INTENT          CONVERSING
       ↓                    ↓
  ENDING ←─────────────────┘
       ↓
   IDLE
```

## 11 Etats

| Etat | Description | LED |
|------|-------------|-----|
| IDLE | Attente, pas de client | Bleu |
| GREETING | Client detecte, salutation | Vert |
| AWAITING_INTENT | Attente intention utilisateur | Blanc |
| SCANNING_PRODUCT | Analyse visuelle en cours | Violet |
| CONFIRMING_TOP3 | Selection parmi Top-3 | Orange |
| SCANNING_BARCODE | Scan code-barres dedie | Violet |
| DISPLAYING_INFO | Affichage fiche produit | Vert |
| CONVERSING | Dialogue avec client | Blanc |
| ADVISING | Conseil en cours | Blanc |
| ENDING | Fin de session | Bleu |
| ERROR | Etat d'erreur | Rouge |

## 20+ Evenements

### Presence
- PERSON_DETECTED, PERSON_LEFT

### Audio
- SPEECH_DETECTED, SPEECH_ENDED, INTENT_RECOGNIZED

### Vision
- PRODUCT_SHOWN, BARCODE_DETECTED
- VLM_HIGH_CONFIDENCE, VLM_MEDIUM_CONFIDENCE, VLM_LOW_CONFIDENCE

### Interaction
- USER_CONFIRMED, USER_DENIED, USER_SELECTED
- QUESTION_ASKED, GOODBYE_DETECTED

### Systeme
- TIMEOUT, ERROR_OCCURRED, NETWORK_ERROR
- RECOVERY_COMPLETE, SECURITY_ALERT

## Timeouts

| Etat | Timeout | Action |
|------|---------|--------|
| IDLE | 60s | Reste en IDLE |
| GREETING | 10s | Retour IDLE |
| AWAITING_INTENT | 30s | Relance ou ENDING |
| SCANNING | 15s | Echec → AWAITING_INTENT |
| CONFIRM | 20s | Timeout → AWAITING_INTENT |
| CONVERSATION | 45s | Fin conversation |

## Fonctionnalites Asynchrones

- `asyncio.Queue` pour traitement evenements
- Taches paralleles: detection presence, flux audio, flux video
- Synchronisation LEDs par etat
- Micro-phrases pre-chargees (< 50ms playback)

## Integration dans la Nouvelle Structure

**Emplacement**: `src/assistant/orchestrator/orchestrator.py`

**Usage**:
```python
from assistant.orchestrator import Orchestrator, OrchestratorConfig

config = OrchestratorConfig(
    idle_timeout=60.0,
    greeting_timeout=10.0
)

orchestrator = Orchestrator(config)

# Injecter les modules
orchestrator.set_database_module(database)
orchestrator.set_security_module(security)
orchestrator.set_vision_module(vision)

# Demarrer
await orchestrator.run()
```
