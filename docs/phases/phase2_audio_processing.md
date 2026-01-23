# Phase 2 - Traitement Audio Entree

## Objectif

Ameliorer la qualite du signal audio capture en environnement bruite (parapharmacie) avant envoi a l'API OpenAI.

## Pipeline de Traitement

```
4 canaux 48kHz → Beamforming → High-Pass → Noise Reduction → AGC → Limiter → Resample 24kHz
```

### 1. Beamforming Directionnel
Combine les 4 canaux en privilegiant la source frontale (client).

**Poids par defaut**:
- Front: 60%
- Left/Right: 25% chacun
- Rear: 5%

**Modes disponibles**:
- `WEIGHTED_SUM`: Somme ponderee simple
- `DELAY_AND_SUM`: Avec compensation de delai
- `ADAPTIVE`: Adaptatif selon energie

### 2. Filtre Passe-Haut
Supprime DC offset et basses frequences (< 80Hz).

### 3. Reduction de Bruit
Spectral gating avec force configurable (0.0-1.0).
- Preserve la voix naturelle
- Estime le profil de bruit automatiquement

### 4. AGC (Automatic Gain Control)
Normalise le volume pour eviter sous-volume et saturation.
- Cible: -20 dB
- Gain max: +20 dB
- Gain min: -10 dB

### 5. Limiteur Doux
Prevention saturation via soft clipping (tanh).

### 6. Resampling
48kHz → 24kHz pour OpenAI Realtime API.

## Presets

| Preset | Usage | Noise Reduction | AGC Max |
|--------|-------|-----------------|---------|
| quiet_room | Bureau calme | 0.1 | 10 dB |
| noisy_room | Environnement bruite | 0.5 | 20 dB |
| far_field | Client a distance | 0.4 | 30 dB |
| close_talk | Client proche | 0.2 | 10 dB |

## Integration dans la Nouvelle Structure

**Emplacement**: `src/assistant/audio/processing.py`

**Usage**:
```python
from assistant.audio import AudioProcessor, get_preset_config

config = get_preset_config('noisy_room')
processor = AudioProcessor(config)

# Traiter audio brut 4 canaux
output_24k = processor.process(raw_48k_4ch)
```

**Tests**:
```bash
python scripts/test_audio.py --preset noisy_room
```
