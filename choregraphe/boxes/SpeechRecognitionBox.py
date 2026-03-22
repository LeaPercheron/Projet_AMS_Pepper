# -*- coding: utf-8 -*-
#
# Choregraphe Python box (Pepper 2.8.8)
# Mode vocal - Reconnaissance vocale via HTTP (approche Walid)
#
# Ce box:
#   1. Écoute le micro de Pepper via ALAudioDevice
#   2. Accumule les données audio jusqu'à détection de silence
#   3. Envoie l'audio en base64 au serveur speech_server.py (port 5001)
#   4. Reçoit la transcription + réponse LLM
#   5. Fait parler Pepper avec ALTextToSpeech
#
# Configuration: modifier les constantes MAC_IP et SERVER_PORT ci-dessous.
#
# Coller ce code dans un box Python Script de Choregraphe.

import base64
import json
import socket
import struct
import threading
import time
import wave
import io

try:
    import urllib2 as urllib_req   # Python 2 (NAOqi)
    PY2 = True
except ImportError:
    import urllib.request as urllib_req  # Python 3
    PY2 = False


class MyClass(GeneratedClass):
    # ===== Configuration utilisateur =====
    MAC_IP      = "192.168.1.50"   # TODO: mettre l'IP de votre ordinateur
    SERVER_PORT = 5001             # Port du serveur speech_server.py
    TABLET_PORT = 8765             # Port WebSocket tablette (information seulement)

    AUDIO_SAMPLE_RATE   = 16000    # Hz
    AUDIO_CHANNEL_FLAG  = 3        # 3 = micro avant (front mic)
    AUDIO_DEINTERLEAVE  = 0

    # Détection de silence (VAD simple)
    SILENCE_THRESHOLD   = 300      # Amplitude RMS pour détecter le silence
    SILENCE_DURATION_S  = 1.2      # Secondes de silence pour couper l'enregistrement
    MIN_SPEECH_DURATION = 0.5      # Durée minimale pour traiter la parole (secondes)
    MAX_RECORD_DURATION = 10.0     # Durée max d'enregistrement (secondes)
    PRE_ROLL_FRAMES     = 3        # Frames à garder avant la parole détectée

    def __init__(self):
        GeneratedClass.__init__(self)
        self._running       = False
        self._recording     = False
        self._audio_service = None
        self._tts_service   = None

        self._audio_buffer  = []     # Frames accumulées
        self._pre_roll      = []     # Buffer pré-roulement
        self._in_speech     = False
        self._silence_frames = 0
        self._speech_frames  = 0
        self._record_start   = 0.0
        self._lock = threading.Lock()

        self._process_thread = None

    def onLoad(self):
        try:
            session = self.session()
            self._audio_service = session.service("ALAudioDevice")
            self._tts_service   = session.service("ALTextToSpeech")
            self.logger.info("[Speech] Services ALAudioDevice/ALTextToSpeech OK")
        except Exception as e:
            self.logger.error("[Speech] Service init error: %s" % str(e))

    def onUnload(self):
        self._stop_recording()

    def onInput_onStart(self):
        """Démarre l'écoute vocale."""
        if self._running:
            return
        self._running = True
        self._start_recording()
        self.logger.info("[Speech] Écoute démarrée")

    def onInput_onStop(self):
        """Arrête l'écoute vocale."""
        self._stop_recording()
        self.onStopped()

    # ===== Capture audio =====

    def _start_recording(self):
        if not self._audio_service:
            self.logger.error("[Speech] ALAudioDevice non disponible")
            return
        try:
            self._audio_service.setClientPreferences(
                self.getName(),
                int(self.AUDIO_SAMPLE_RATE),
                int(self.AUDIO_CHANNEL_FLAG),
                int(self.AUDIO_DEINTERLEAVE),
            )
            self._audio_service.subscribe(self.getName())
            self.logger.info("[Speech] Micro subscrit (%d Hz)" % self.AUDIO_SAMPLE_RATE)
        except Exception as e:
            self.logger.error("[Speech] Subscribe error: %s" % str(e))

    def _stop_recording(self):
        if not self._running:
            return
        self._running = False
        try:
            if self._audio_service:
                self._audio_service.unsubscribe(self.getName())
        except Exception:
            pass
        if self._process_thread and self._process_thread.is_alive():
            self._process_thread.join(3.0)
        self.logger.info("[Speech] Écoute arrêtée")

    def processRemote(self, nbOfChannels, nbrOfSamplesByChannel, aTimeStamp, buffer):
        """
        Callback audio de ALAudioDevice.
        Appelé en continu avec les données micro.
        """
        if not self._running or not buffer:
            return
        if self._process_thread and self._process_thread.is_alive():
            # Un traitement est en cours, ignorer les nouvelles frames
            return

        try:
            raw = bytes(bytearray(buffer))
            self._process_audio_frame(raw, nbrOfSamplesByChannel)
        except Exception as e:
            self.logger.error("[Speech] processRemote error: %s" % str(e))

    def _rms(self, data):
        """Calcule le RMS (volume) d'une frame audio PCM16."""
        try:
            import struct as _struct
            n = len(data) // 2
            if n == 0:
                return 0
            samples = _struct.unpack("<%dh" % n, data[:n * 2])
            total = sum(s * s for s in samples)
            return int((total / n) ** 0.5)
        except Exception:
            return 0

    def _process_audio_frame(self, raw, samples_per_channel):
        """
        VAD simple : accumule les frames et détecte la fin de parole.
        """
        rms = self._rms(raw)
        is_speech = rms > self.SILENCE_THRESHOLD

        frames_per_second = float(self.AUDIO_SAMPLE_RATE) / max(1, samples_per_channel)

        with self._lock:
            if not self._in_speech:
                # Garder le pré-roulement
                self._pre_roll.append(raw)
                if len(self._pre_roll) > self.PRE_ROLL_FRAMES:
                    self._pre_roll.pop(0)

                if is_speech:
                    # Début de parole détecté
                    self._in_speech = True
                    self._audio_buffer = list(self._pre_roll)
                    self._pre_roll = []
                    self._silence_frames = 0
                    self._speech_frames = 1
                    self._record_start = time.time()
            else:
                # En cours d'enregistrement
                self._audio_buffer.append(raw)
                elapsed = time.time() - self._record_start

                if is_speech:
                    self._silence_frames = 0
                    self._speech_frames += 1
                else:
                    self._silence_frames += 1

                silence_s = self._silence_frames / max(1.0, frames_per_second)
                speech_s  = self._speech_frames  / max(1.0, frames_per_second)

                if silence_s >= self.SILENCE_DURATION_S or elapsed >= self.MAX_RECORD_DURATION:
                    # Fin de parole détectée
                    if speech_s >= self.MIN_SPEECH_DURATION:
                        buf = list(self._audio_buffer)
                        n_samples = samples_per_channel
                        # Lancer le traitement dans un thread séparé
                        self._process_thread = threading.Thread(
                            target=self._send_to_server,
                            args=(buf, n_samples),
                            name="speech-process"
                        )
                        self._process_thread.daemon = True
                        self._process_thread.start()
                    else:
                        self.logger.info("[Speech] Parole trop courte, ignorée")

                    # Reset
                    self._in_speech = False
                    self._audio_buffer = []
                    self._speech_frames = 0
                    self._silence_frames = 0

    # ===== Envoi au serveur et lecture de la réponse =====

    def _send_to_server(self, frames, samples_per_channel):
        """
        Encode les frames en WAV, envoie au serveur speech_server.py,
        puis fait parler Pepper avec la réponse.
        """
        self.logger.info("[Speech] Envoi audio au serveur (%d frames)" % len(frames))

        try:
            # Construire le WAV en mémoire
            wav_buf = io.BytesIO()
            n_channels   = 1
            sample_width = 2  # 16-bit
            sample_rate  = int(self.AUDIO_SAMPLE_RATE)

            wf = wave.open(wav_buf, "wb")
            wf.setnchannels(n_channels)
            wf.setsampwidth(sample_width)
            wf.setframerate(sample_rate)
            for frame in frames:
                wf.writeframes(frame)
            wf.close()
            wav_buf.seek(0)
            raw_wav = wav_buf.read()

            # Paramètres wave (format attendu par speech_server.py / googleSR_server_test.py)
            params = (
                n_channels,
                sample_width,
                sample_rate,
                len(raw_wav) // (n_channels * sample_width),
                "NONE",
                "not compressed"
            )

            # Encoder en base64
            data_b64   = base64.b64encode(raw_wav).decode("utf-8")
            params_b64 = base64.b64encode(str(params).encode("utf-8")).decode("utf-8")

            # Préparer la requête HTTP
            url = "http://%s:%d/process" % (self.MAC_IP, self.SERVER_PORT)
            payload = json.dumps({"data": data_b64, "params": params_b64})

            if PY2:
                req = urllib_req.Request(
                    url,
                    data=payload,
                    headers={"Content-Type": "application/json"}
                )
                response = urllib_req.urlopen(req, timeout=15)
                result = json.loads(response.read().decode("utf-8"))
            else:
                import urllib.request
                req = urllib.request.Request(
                    url,
                    data=payload.encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    result = json.loads(resp.read().decode("utf-8"))

            sentence = result.get("sentence") or ""
            tts_text = result.get("tts") or result.get("response") or ""

            if sentence:
                self.logger.info("[Speech] Transcription: %s" % sentence)
            if tts_text:
                self.logger.info("[Speech] Réponse: %s" % tts_text[:80])
                self._speak(tts_text)
            else:
                self.logger.info("[Speech] Aucune réponse reçue")

        except Exception as e:
            self.logger.error("[Speech] Erreur envoi serveur: %s" % str(e))

    def _speak(self, text):
        """Fait parler Pepper via ALTextToSpeech."""
        if not text or not self._tts_service:
            return
        try:
            self._tts_service.say(str(text))
        except Exception as e:
            self.logger.error("[Speech] TTS error: %s" % str(e))
