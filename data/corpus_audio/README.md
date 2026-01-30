# Corpus Audio - Tests Sans Pepper

Fichiers audio pour tester le pipeline audio en mode simulation.

## Generation

```bash
# Generer le corpus de test
python scripts/test_audio_pipeline.py --generate-test-corpus
```

## Fichiers generes

| Fichier | Description | Format |
|---------|-------------|--------|
| `speech_clean_48k.wav` | Parole simulee propre | 48kHz mono |
| `speech_noisy_48k.wav` | Parole + bruit blanc | 48kHz mono |
| `test_4ch_48k.wav` | Signal test 4 canaux | 48kHz 4ch |
| `silence_48k.wav` | Silence | 48kHz mono |

## Utilisation

### Test du pipeline complet

```bash
python scripts/test_audio_pipeline.py
```

### Test avec fichier specifique

```bash
python scripts/test_audio_pipeline.py --input data/corpus_audio/speech_clean_48k.wav
```

## Ajout de vos propres fichiers

Pour tester avec de vrais enregistrements Pepper :

1. Enregistrez l'audio 4 canaux depuis Pepper
2. Placez les fichiers `.wav` dans ce dossier
3. Nommez-les selon le format : `{description}_{channels}ch_{samplerate}.wav`

Exemple : `conversation_reelle_4ch_48k.wav`

## Format attendu

- **Sample rate**: 48000 Hz (entree Pepper)
- **Bit depth**: 16-bit PCM
- **Canaux**: 4 (microphones Pepper) ou 1 (mono)
