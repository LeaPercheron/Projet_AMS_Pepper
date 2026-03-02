# Voice Test Pepper (mini projet temporaire)

Ce mini projet sert à tester uniquement la boucle vocale:

`Client tablette -> micro Pepper -> transcription OpenAI -> réponse OpenAI -> voix Pepper + retour tablette`

Sans dépendance au scan visuel/code-barres.

## 1) Lancer la page tablette de test

```bash
cd /Users/leapercheron/Master/Semestre_2/Projet_AMS_2/Projet/depot/Projet_AMS_Pepper/voice_test/tablet
python3 -m http.server 8081 --bind 0.0.0.0
```

## 2) Lancer le serveur vocal test

```bash
cd /Users/leapercheron/Master/Semestre_2/Projet_AMS_2/Projet/depot/Projet_AMS_Pepper
PYTHONPATH=src python3 voice_test/main.py \
  --pepper-ip 10.120.19.96 \
  --ws-host 0.0.0.0 \
  --ws-port 8870 \
  --tablet-url "http://10.120.14.182:8081/index.html?ws=ws://10.120.14.182:8870"
```

Option de secours (capture audio via SSH bridge):

```bash
PYTHONPATH=src python3 voice_test/main.py \
  --pepper-ip 10.120.19.96 \
  --ssh-bridge \
  --ssh-user nao \
  --ssh-port 22 \
  --ws-host 0.0.0.0 \
  --ws-port 8870 \
  --tablet-url "http://10.120.14.182:8081/index.html?ws=ws://10.120.14.182:8870"
```

## Notes

- Requiert `OPENAI_API_KEY`.
- Debug audio capture: `export PEPPER_AUDIO_DEBUG=1`
- Front mic prioritaire en fallback recorder (désactivable avec `PEPPER_AUDIO_RECORDER_FRONT_ONLY=0`).
- Chemin WAV robot personnalisable: `export PEPPER_AUDIO_RECORDER_PATH=/home/nao/pepper_capture_chunk.wav`
- En mode front-only, `voice_test` force automatiquement le pipeline STT en mono 16 kHz.
- Gain micro logiciel (avant STT): `export OPENAI_HTTP_INPUT_GAIN=2.5` (exemple).
- Si OpenAI transcription est indisponible, un fallback STT local `mlx-whisper` peut être utilisé.
- Installation fallback local: `python3 -m pip install mlx-whisper`
- Modèle local auto-détecté dans `~/.cache/huggingface/hub` (ou forcer via `OPENAI_HTTP_LOCAL_STT_PATH`).
- Si OpenAI texte est indisponible, `voice_test` répond en mode echo vocal pour valider la boucle micro->Pepper.
- Si aucune parole n'est détectée, la tablette affiche un message explicite.
- Projet temporaire: dossier `voice_test/` supprimable quand l'intégration principale est validée.
