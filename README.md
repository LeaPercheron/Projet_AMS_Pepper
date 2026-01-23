# Parapharma Assistant

Assistant vocal pour robot Pepper specialise dans les produits capillaires en parapharmacie.

## Apercu

Ce projet implemente un assistant conversationnel sur robot Pepper permettant aux clients de:
- Identifier des produits capillaires par vision (VLM) ou code-barres
- Obtenir des informations (prix, usage, ingredients)
- Poser des questions via dialogue vocal naturel

**Securite integree**: L'assistant refuse les conseils medicaux et detecte les medicaments.

## Demarrage Rapide

### 1. Installation

```bash
# Cloner le projet
git clone <repository>
cd Projet_AMS_Pepper

# Creer environnement virtuel
python3 -m venv venv
source venv/bin/activate

# Installer les dependances
pip install -e .

# Ou avec extras (VLM + dev)
pip install -e ".[all]"
```

### 2. Configuration

```bash
# Copier le fichier exemple
cp .env.example .env

# Editer avec votre cle API OpenAI
nano .env
```

```env
OPENAI_API_KEY=sk-your-api-key-here
PEPPER_IP=192.168.1.100  # Optionnel, vide = simulation
```

### 3. Lancement

```bash
# Mode simulation (sans robot)
python -m assistant.main --simulation

# Mode avec Pepper
python -m assistant.main --pepper-ip 192.168.1.100

# Mode debug
python -m assistant.main --simulation --debug
```

## Structure du Projet

```
parapharma-assistant/
├── README.md                    # Ce fichier
├── pyproject.toml               # Configuration projet Python
├── .env.example                 # Template variables environnement
├── config/
│   └── config.yaml              # Configuration principale
│
├── src/assistant/               # Code source principal
│   ├── main.py                  # Point d'entree
│   ├── config.py                # Gestion configuration
│   ├── logger.py                # Logging JSONL
│   │
│   ├── adapters/                # Hardware (Pepper, Mock)
│   ├── audio/                   # Capture, traitement, VAD
│   ├── realtime/                # Client OpenAI Realtime
│   ├── vision/                  # VLM, code-barres
│   ├── database/                # SQLite produits
│   ├── safety/                  # Filtres securite
│   └── orchestrator/            # Machine a etats
│
├── tablet/                      # Interface tablette (HTML/JS)
│   ├── index.html
│   ├── styles.css
│   ├── app.js
│   └── server.py
│
├── scripts/                     # Scripts utilitaires
│   ├── test_audio.py
│   ├── test_vision.py
│   └── run_demo.py
│
├── tests/                       # Tests unitaires
│
├── data/                        # Donnees
│   ├── products.db
│   └── blacklist.json
│
└── docs/                        # Documentation
    ├── architecture.md
    └── phases/                  # Historique des phases
```

## Modes d'Execution

| Mode | Description | Commande |
|------|-------------|----------|
| **Simulation** | Sans hardware, pour tests | `--simulation` |
| **Development** | Avec Pepper, logs verbeux | (par defaut) |
| **Production** | Deploiement final | `--production` |
| **Test** | Timeouts courts | `--test` |

## Fonctionnalites

### Vision
- Identification VLM (Qwen2-VL-2B) en ~500ms
- Detection code-barres EAN-13
- Confiance: Haute (>85%), Moyenne (60-85%), Basse (<60%)

### Audio
- Beamforming 4 canaux → mono
- Reduction de bruit adaptative
- Half-duplex (anti-feedback)

### Dialogue
- OpenAI Realtime API (GPT-4o)
- VAD serveur avec presets
- Reponses concises (2-3 phrases)

### Securite
- 80+ mots-cles medicaux bloques
- Blacklist 100+ medicaments
- 4 scenarios de securite obligatoires

## Tests

```bash
# Test module audio
python scripts/test_audio.py

# Test module vision
python scripts/test_vision.py

# Demo interactive
python scripts/run_demo.py
```

## Documentation

- [Architecture](docs/architecture.md) - Vue technique complete
- [Phases](docs/phases/) - Historique du developpement:
  - [Phase 0](docs/phases/phase0_validation.md) - Validation hardware
  - [Phase 1](docs/phases/phase1_audio_pipeline.md) - Pipeline audio
  - [Phase 2](docs/phases/phase2_audio_processing.md) - Traitement audio
  - [Phase 3](docs/phases/phase3_openai_realtime.md) - OpenAI Realtime
  - [Phase 4](docs/phases/phase4_vad_dialogue.md) - VAD et dialogue
  - [Phase 5](docs/phases/phase5_vision.md) - Vision VLM
  - [Phase 6](docs/phases/phase6_database.md) - Base de donnees
  - [Phase 7](docs/phases/phase7_security.md) - Securite
  - [Phase 9](docs/phases/phase9_orchestrator.md) - Orchestrateur
  - [Phase 10](docs/phases/phase10_tablet.md) - Interface tablette
  - [Phase 11](docs/phases/phase11_integration.md) - Integration

## Prerequis

- Python 3.10+
- Mac avec Apple Silicon (M1/M2/M3/M4) pour VLM
- Robot Pepper avec NAOqi SDK (optionnel)
- Cle API OpenAI

## Licence

Projet academique - Master 2 AMS
