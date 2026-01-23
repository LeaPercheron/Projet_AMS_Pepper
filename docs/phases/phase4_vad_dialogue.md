# Phase 4 - VAD et Gestion du Dialogue

## Objectif

Optimiser la detection de parole (VAD) et implementer la strategie half-duplex pour eviter les boucles audio.

## VAD (Voice Activity Detection)

### Presets par Situation

| Preset | Threshold | Silence (ms) | Usage |
|--------|-----------|--------------|-------|
| DEFAULT | 0.5 | 500 | Standard |
| HESITANT | 0.4 | 800 | Personnes agees, hesitantes |
| FAST_SPEAKER | 0.6 | 350 | Locuteurs rapides |
| NOISY | 0.7 | 600 | Environnement bruite |
| ELDERLY | 0.4 | 1200 | Longues pauses |

### Detection des Hesitations
- "euh...", "hmm...", "alors..."
- Tolerance aux pauses dans la phrase
- Non-declenchement premature de la reponse

## Half-Duplex

### Probleme
Quand Pepper parle, ses microphones captent sa propre voix, creant potentiellement une boucle.

### Solution
```
LISTENING → (audio normal) → SPEAKING → (silence) → COOLDOWN → LISTENING
```

**Etats**:
- **LISTENING**: Audio envoye normalement a OpenAI
- **SPEAKING**: Audio remplace par silence (zeros)
- **COOLDOWN**: Periode tampon apres fin de parole (200ms)

### Parametres
- Cooldown: 200ms
- Fade duration: 20ms (evite clicks)
- Interruption: Detection parole pendant SPEAKING → retour LISTENING

## Systeme de Prompts

### Structure
1. **Role de base**: Assistant parapharmacie specialise capillaire
2. **Regles de securite**: Pas de conseil medical
3. **Contexte produit**: Injecte dynamiquement
4. **Style**: VERBOSE, CONCISE, ou FRIENDLY

### Injection Contexte Produit
```python
prompt = base_prompt + f"""
Produit identifie: {product.name}
Marque: {product.brand}
Prix: {product.price}€
Usage: {product.usage}
"""
```

## Integration dans la Nouvelle Structure

**Emplacement**:
- `src/assistant/audio/half_duplex.py`
- `src/assistant/audio/vad_config.py`
- `src/assistant/audio/prompt_system.py`

**Usage**:
```python
from assistant.audio import HalfDuplexManager, SpeakingState

manager = HalfDuplexManager()

# Quand Pepper parle
manager.start_speaking()

# Filtrer audio entrant
filtered = manager.filter_input_audio(audio_bytes)

# Quand Pepper arrete
manager.stop_speaking()
```
