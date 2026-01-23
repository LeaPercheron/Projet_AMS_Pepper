# Phase 0 - Validation Hardware

## Objectif

Valider la connectivite et le fonctionnement de tous les composants hardware necessaires au projet:
- Connexion reseau avec le robot Pepper
- Camera et capteurs visuels
- Microphones (array 4 canaux)
- Haut-parleurs
- Modele VLM sur Apple Silicon

## Fichiers Originaux

```
phase0_validation/
├── test_1_connection.py    # Test connexion TCP/IP Pepper
├── test_2_camera.py        # Test camera et flux video
├── test_3_audio_capture.py # Test microphones 4 canaux
├── test_4_audio_playback.py # Test haut-parleurs
├── test_5_vlm.py           # Test chargement modele VLM
└── run_phase0_validation.py # Script d'orchestration
```

## Tests Realises

### 1. Connexion Reseau
- Verification connexion TCP/IP vers Pepper (port 9559 NAOqi)
- Test latence reseau
- Validation cable RJ45

### 2. Camera
- Acquisition flux video depuis camera frontale
- Resolution VGA (640x480)
- Verification colorspace RGB

### 3. Audio Capture
- Test array 4 microphones
- Frequence: 48kHz
- Format: 16-bit PCM interleaved
- Canaux: Front, Rear, Left, Right

### 4. Audio Playback
- Test haut-parleurs stereo
- Frequence: 48kHz
- Verification volume et qualite

### 5. VLM (Vision Language Model)
- Chargement modele mlx-vlm sur M4 Pro
- Modele: Qwen2-VL-2B-Instruct-4bit
- Temps de chargement: ~3s
- Inference test reussie

## Integration dans la Nouvelle Structure

Les tests de validation sont maintenant accessibles via:
```bash
python scripts/test_audio.py
python scripts/test_vision.py
```

Le mode simulation (`--simulation`) permet de tester sans hardware.
