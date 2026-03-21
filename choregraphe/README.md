# Choregraphe Bridge (Pepper 2.8.8)

This folder contains ready-to-paste Python box code for Choregraphe.

Goal:
- Stream Pepper audio to the Mac backend (`assistant.main`) on TCP `5555`
- Stream Pepper camera frames to the Mac backend on TCP `5557`
- Receive TTS commands from the Mac backend on TCP `5558`

The backend side is already implemented in:
- `src/assistant/adapters/choregraphe_adapter.py`

## Files

- `boxes/BridgeSupervisorBox.py`
  - One-box behavior (audio + video + control TTS server).
  - Recommended for first integration.

## Choregraphe setup (2.8.8)

1. Open Choregraphe and connect to Pepper.
2. Create a new behavior package (for example `ParapharmaBridge`).
3. Add a `Python Script` box.
4. Rename it to `BridgeSupervisor`.
5. Copy/paste the full content of `boxes/BridgeSupervisorBox.py`.
6. Edit only this variable in the script:
   - `MAC_IP = "..."` -> set your Mac LAN IP.
7. Wire behavior:
   - connect package `onStart` to `BridgeSupervisor.onStart`
   - connect `BridgeSupervisor.onStopped` to package `onStopped`
8. Save the behavior.
9. Click `Play` on the behavior.

## Backend launch (Mac)

Run the project backend from the repo root:

```bash
PYTHONPATH=src python3 -m assistant.main --pepper-ip <IP_PEPPER> --tablet-url "http://<IP_MAC>:8080/index.html?ws=ws://<IP_MAC>:8765"
```

`Realtime` is disabled in code on this branch; voice path is HTTP + whisper fallback.

## Expected logs

On Choregraphe box output:
- `[Bridge] Audio connected to ...:5555`
- `[Bridge] Video connected to ...:5557`
- `[Bridge] Control server listening on 0.0.0.0:5558`

On backend logs:
- `Adaptateur: ChoregrapheAdapter (connecte)`
- `OpenAI Realtime: desactive ... HTTP/Whisper`
- `Fallback vocal HTTP: actif (transcription=whisper-1)`
- `Flux audio connecte` (from choregraphe adapter)

## Troubleshooting

- No voice transcript:
  - Verify `MAC_IP` in the box script.
  - Check Pepper can reach Mac on ports `5555/5557/5558`.
  - Check same network/VLAN.
- No spoken answer on Pepper:
  - `BridgeSupervisor` must be running (control server on `5558`).
  - `ALTextToSpeech` service must be available on Pepper.
- Tablet UI works but no voice:
  - ensure you actually click `start_voice_question` then `stop_voice_question`.
