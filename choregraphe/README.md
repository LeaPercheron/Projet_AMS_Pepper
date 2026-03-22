# Choregraphe - Pepper Parapharmacie

Ce dossier contient les comportements et boxes Choregraphe pour le projet.

---

## Architecture globale (mode Choregraphe)

```
Pepper Robot (Choregraphe)          Ordinateur (Python)
┌─────────────────────────┐         ┌──────────────────────────────┐
│ BridgeSupervisorBox.py  │──────►  │ speech_server.py (Flask:5001)│
│  • Audio 16kHz → TCP    │  audio  │  • Google SR (comme Walid)   │
│  • Vidéo → TCP          │         │  • Réponse LLM (GPT-4o-mini) │
│  • TTS ← TCP            │◄──────  │  • Identification produit     │
│                         │  TTS    │                              │
│ SpeechRecognitionBox.py │──────►  │ POST /process (audio→réponse)│
│  • Audio → HTTP POST    │         │ POST /google  (transcription) │
│  • Réponse → TTS        │◄──────  │ POST /ask     (LLM)          │
└─────────────────────────┘         │ GET  /products (liste)       │
                                    │                              │
                                    │ tablet/server.py (WS:8765)   │
                                    │  • Interface tablette        │
                                    └──────────────────────────────┘
```

---

## Fichiers

### `boxes/BridgeSupervisorBox.py`
Bridge TCP complet pour les flux audio et vidéo :
- Envoie l'audio Pepper → Ordinateur:5555
- Envoie la vidéo Pepper → Ordinateur:5557
- Reçoit les commandes TTS Ordinateur → Pepper:5558

**Configuration :** modifier `MAC_IP` avec l'IP de votre ordinateur.

### `boxes/SpeechRecognitionBox.py`
Box vocal basé sur l'approche de Walid (Google Speech Recognition via HTTP) :
- Capture audio depuis `ALAudioDevice`
- Détecte la fin de parole (VAD simple par seuil RMS)
- Envoie l'audio en base64 au serveur `speech_server.py` (POST /process)
- Fait parler Pepper avec la réponse (ALTextToSpeech)

**Configuration :** modifier `MAC_IP` avec l'IP de votre ordinateur.

---

## Mise en place rapide

### 1. Démarrer le serveur Python sur votre ordinateur

```bash
# Installer les dépendances
pip install flask SpeechRecognition pydub openai websockets python-dotenv

# Configurer l'environnement
cp .env.example .env
# Éditer .env et renseigner OPENAI_API_KEY

# Lancer le serveur
python speech_server.py
```

### 2. Configurer les boxes Choregraphe

Dans `SpeechRecognitionBox.py` **et** `BridgeSupervisorBox.py`, remplacer :
```python
MAC_IP = "192.168.1.50"   # ← mettre l'IP de votre ordinateur
```

### 3. Ajouter SpeechRecognitionBox dans Choregraphe

1. Ouvrir le projet `Pepper_Parapharmacie` dans Choregraphe 2.8.8
2. Créer un box `Python Script`
3. Le renommer `SpeechRecognition`
4. Coller le contenu de `boxes/SpeechRecognitionBox.py`
5. Connecter : package `onStart` → `SpeechRecognition.onStart`
6. Connecter : `SpeechRecognition.onStopped` → package `onStopped`
7. Sauvegarder et lancer

### 4. Tablette

Accès à l'interface tablette via :
- Directement dans Pepper : `http://<IP_ORDINATEUR>:8080/tablet/index.html`
- Ou WebSocket : `ws://<IP_ORDINATEUR>:8765`

---

## Flux vocal (approche Walid)

```
1. Utilisateur parle → Micro ALAudioDevice
2. SpeechRecognitionBox détecte la fin de parole (VAD RMS)
3. Encode l'audio en base64 WAV
4. HTTP POST /process → speech_server.py
5. speech_server.py transcrit avec Google Speech Recognition (fr-FR)
6. Si Google SR échoue → fallback Whisper (si OPENAI_API_KEY défini)
7. speech_server.py génère une réponse avec GPT-4o-mini
8. Retourne {"sentence": "...", "tts": "réponse..."}
9. SpeechRecognitionBox fait dire la réponse à Pepper (ALTextToSpeech)
```

---

## Ports réseau

| Port | Service | Direction |
|------|---------|-----------|
| 5001 | Flask speech_server.py | Ordinateur écoute |
| 5555 | Audio TCP (BridgeSupervisorBox) | Pepper → Ordinateur |
| 5557 | Vidéo TCP (BridgeSupervisorBox) | Pepper → Ordinateur |
| 5558 | Contrôle TTS TCP | Ordinateur → Pepper |
| 8765 | WebSocket tablette | Ordinateur écoute |

---

## Logs attendus

**Dans Choregraphe (SpeechRecognitionBox) :**
```
[Speech] Services ALAudioDevice/ALTextToSpeech OK
[Speech] Écoute démarrée
[Speech] Micro subscrit (16000 Hz)
[Speech] Envoi audio au serveur (12 frames)
[Speech] Transcription: "quel shampooing pour cheveux gras ?"
[Speech] Réponse: "Je vous recommande le shampooing..."
```

**Dans speech_server.py :**
```
[INFO] Base de données: 42 produits
[INFO] Transcription Google SR: 'quel shampooing pour cheveux gras ?'
[INFO] Réponse LLM: 'Je vous recommande...'
```

---

## Dépannage

- **Pas de transcription** : vérifier que `MAC_IP` est correct et que Pepper peut joindre le port 5001
- **Google SR échoue** : vérifier la connexion Internet du robot / de l'ordinateur
- **Pas de réponse LLM** : vérifier `OPENAI_API_KEY` dans `.env`
- **Tablette ne se connecte pas** : vérifier que `speech_server.py` est lancé (serveur WebSocket sur port 8765)
