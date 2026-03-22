#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import json
import re
import random
import os
from flask import Flask, request, jsonify

import base64
import speech_recognition as sr
import wave
from ast import literal_eval
from pydub import AudioSegment  # <--- Nouvelle importation

def speechRecognition(data, params):
    r = sr.Recognizer()
    audioFileName = 'test.wav'
    
    # Décodage des données reçues
    data = base64.b64decode(data)
    params = base64.b64decode(params)
    params = literal_eval(params.decode("utf-8"))

    # 1. Écriture initiale du fichier (tel que reçu du robot)
    wave_write = wave.open(audioFileName, "w")
    wave_write.setparams(params)
    wave_write.writeframes(data)
    wave_write.close()

    # 2. Correction : Conversion en MONO si nécessaire
    # On recharge le fichier avec pydub pour le normaliser
    audio = AudioSegment.from_wav(audioFileName)
    if audio.channels > 2:
        # On force en mono (1 canal) pour que SpeechRecognition ne crash pas
        audio = audio.set_channels(1)
        audio.export(audioFileName, format="wav")

    # 3. Lecture par SpeechRecognition
    audioFile = None
    try:
        with sr.AudioFile(audioFileName) as source:
            audioFile = r.record(source)
            
        text = r.recognize_google(audioFile, language="fr-FR")
        return text
    except Exception as e:
        print(f"Erreur lors de la reconnaissance : {e}")
        return None


app = Flask(__name__)

@app.route("/google", methods=["POST"])
def transcribe():
    req_data = request.get_json(force=True)

    # Récupération de la transcription
    result_from_google = speechRecognition(req_data['data'], req_data['params'])

    print(f"Résultat Google : {result_from_google}")
    
    # Envoi de la réponse
    reply = {"sentence": result_from_google}
    return jsonify(reply)

if __name__ == "__main__":
    # Note : debug=True est utile en développement pour voir les erreurs en direct
    app.run(host='0.0.0.0', port=5001, debug=False)