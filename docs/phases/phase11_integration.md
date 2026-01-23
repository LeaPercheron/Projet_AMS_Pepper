# Phase 11 - Integration Systeme

## Objectif

Assembler tous les modules en un systeme coherent avec configuration unifiee et demarrage simplifie.

## Modes d'Execution

| Mode | Description | Commande |
|------|-------------|----------|
| DEVELOPMENT | Tests locaux, logs verbeux | `python -m assistant.main` |
| PRODUCTION | Deploiement, logs minimaux | `python -m assistant.main --production` |
| SIMULATION | Sans hardware | `python -m assistant.main --simulation` |
| TEST | Timeouts courts | `python -m assistant.main --test` |

## Sequence d'Initialisation

```
1. Charger configuration (config.yaml / env)
2. Initialiser adaptateur (Pepper ou Mock)
3. Initialiser database (Phase 6)
4. Initialiser securite (Phase 7)
5. Initialiser vision (Phase 5)
6. Initialiser OpenAI client (Phase 3)
7. Initialiser serveur tablette (Phase 10)
8. Initialiser orchestrateur (Phase 9)
9. Demarrer toutes les taches async
```

## Configuration Centralisee

### Fichier: config/config.yaml
```yaml
mode: development

pepper:
  ip: ""
  port: 9559

openai:
  model: gpt-4o-realtime-preview-2024-10-01
  voice: shimmer

vision:
  model: mlx-community/Qwen2-VL-2B-Instruct-4bit
  confidence_high: 0.85

database:
  path: data/products.db

security:
  strict_mode: true

orchestrator:
  idle_timeout: 60
  greeting_timeout: 10

tablet:
  host: 0.0.0.0
  port: 8765

logging:
  level: INFO
  format: jsonl
```

### Variables d'Environnement
```bash
OPENAI_API_KEY=sk-...
PEPPER_IP=192.168.1.100
RUN_MODE=development
```

## Logging JSONL

Format structure pour analyse:
```jsonl
{"timestamp":"2024-01-22T14:30:00","level":"INFO","event":"system_start","data":{"mode":"development"}}
{"timestamp":"2024-01-22T14:30:01","level":"INFO","event":"state_change","data":{"from":"IDLE","to":"GREETING"}}
```

### Evenements Logges
- system_start, system_stop
- state_change
- product_identified
- security_alert
- latency_measure
- session_start, session_end

## Integration dans la Nouvelle Structure

**Point d'entree**: `src/assistant/main.py`

**Usage**:
```bash
# Mode simulation
python -m assistant.main --simulation

# Avec Pepper
python -m assistant.main --pepper-ip 192.168.1.100

# Production
python -m assistant.main --production --pepper-ip 192.168.1.100

# Debug
python -m assistant.main --debug
```

**Import programmatique**:
```python
from assistant.main import PepperAssistant
from assistant.config import get_simulation_config

config = get_simulation_config()
assistant = PepperAssistant(config)

await assistant.setup()
await assistant.run()
```
