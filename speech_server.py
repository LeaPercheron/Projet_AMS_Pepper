#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Serveur principal - Pepper Parapharmacie (mode Choregraphe)
#
# Ce serveur gère:
#   1. Transcription vocale  → OpenAI Whisper (whisper-1)
#   2. Réponse LLM           → OpenAI GPT-4o-mini
#   3. Identification produit → OpenAI GPT-4o Vision (image base64)
#   4. Interface tablette    → WebSocket (port 8765)
#
# Lancement:
#   python speech_server.py
#
# Variables d'environnement (voir .env):
#   OPENAI_API_KEY   - clé API OpenAI (obligatoire)
#   PEPPER_IP        - IP du robot (optionnel, pour TTS direct qi)
#   FLASK_PORT       - port Flask (défaut: 5001)
#   TABLET_PORT      - port WebSocket tablette (défaut: 8765)
#   DB_PATH          - chemin vers products.db (défaut: data/products.db)

import argparse
import asyncio
import base64
import io
import json
import logging
import os
import sys
import threading
import wave
from pathlib import Path
from typing import Optional

# ─── Charger .env ──────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    _root = Path(__file__).resolve().parent
    load_dotenv(_root / ".env")
    load_dotenv()
except ImportError:
    pass

from flask import Flask, request, jsonify

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    print("[WARN] openai non installé: pip install openai")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("speech_server")

# ─── Configuration ─────────────────────────────────────────────────────────────

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
PEPPER_IP      = os.getenv("PEPPER_IP", "")
PEPPER_PORT    = int(os.getenv("PEPPER_PORT", "9559"))
FLASK_PORT     = int(os.getenv("FLASK_PORT", "5001"))
TABLET_PORT    = int(os.getenv("TABLET_PORT", "8765"))
DB_PATH        = os.getenv("DB_PATH", str(Path(__file__).parent / "data" / "products.db"))
BLACKLIST_PATH = os.getenv("BLACKLIST_PATH", str(Path(__file__).parent / "data" / "blacklist.json"))

SYSTEM_PROMPT = (
    "Tu es un assistant vocal de parapharmacie spécialisé cheveux dans un magasin Pepper. "
    "Réponds en français, 2 à 4 phrases maximum, ton clair et professionnel. "
    "Tu peux répondre aux questions capillaires courantes (cheveux gras, secs, "
    "pellicules, usage d'un shampooing, fréquence d'utilisation, comparaison de produits). "
    "Réponds DIRECTEMENT à la question posée. "
    "Tu ne dois PAS faire de diagnostic médical ni de prescription. "
    "En cas de question médicale explicite, réponds exactement: "
    "'Je ne peux pas répondre à cette question. Je vous invite à consulter le pharmacien.'"
)

VISION_PROMPT = (
    "Tu es un expert en identification de produits de parapharmacie. "
    "Regarde cette image et identifie le produit capillaire visible. "
    "Réponds en JSON strict avec ces champs: "
    "{\"name\": \"<nom du produit>\", \"brand\": \"<marque>\", \"type\": \"<type: shampooing/soin/masque/etc>\", "
    "\"hair_type\": \"<type cheveux ciblé>\", \"confidence\": <0.0 à 1.0>}. "
    "Si tu ne peux pas identifier le produit, réponds: {\"name\": null, \"confidence\": 0.0}."
)

# ─── Clients globaux ────────────────────────────────────────────────────────────

_openai_client: Optional[object] = None
_database      = None
_security      = None
_tablet_clients: set = set()
_tablet_lock   = threading.Lock()


def get_openai_client():
    global _openai_client
    if _openai_client is None and OPENAI_AVAILABLE and OPENAI_API_KEY:
        _openai_client = OpenAI(api_key=OPENAI_API_KEY)
    return _openai_client


def get_database():
    global _database
    if _database is None:
        try:
            sys.path.insert(0, str(Path(__file__).parent / "src"))
            from assistant.database import ProductDatabase
            if Path(DB_PATH).exists():
                _database = ProductDatabase(DB_PATH)
                count = _database.count_products()
                logger.info(f"Base de données: {count} produits ({DB_PATH})")
            else:
                logger.warning(f"Base de données non trouvée: {DB_PATH}")
        except Exception as e:
            logger.warning(f"Base de données indisponible: {e}")
    return _database


def get_security():
    global _security
    if _security is None:
        try:
            sys.path.insert(0, str(Path(__file__).parent / "src"))
            from assistant.safety import SecurityModule, SecurityConfig
            _security = SecurityModule(SecurityConfig(), blacklist_path=BLACKLIST_PATH)
            logger.info("Module sécurité: OK")
        except Exception as e:
            logger.warning(f"Module sécurité indisponible: {e}")
    return _security


# ─── Transcription Whisper ──────────────────────────────────────────────────────

def transcribe_whisper(data_b64: str, params_b64: str) -> Optional[str]:
    """
    Transcrit un enregistrement audio WAV via OpenAI Whisper.

    Reçoit les mêmes paramètres que l'approche Walid (base64 WAV + params),
    mais utilise Whisper au lieu de Google SR.
    """
    client = get_openai_client()
    if client is None:
        logger.error("OpenAI non configuré (OPENAI_API_KEY manquant)")
        return None

    try:
        raw_data = base64.b64decode(data_b64)
        raw_params = base64.b64decode(params_b64)

        from ast import literal_eval
        params = literal_eval(raw_params.decode("utf-8"))

        # Reconstruire le fichier WAV en mémoire
        buf = io.BytesIO()
        with wave.open(buf, "w") as wf:
            wf.setparams(params)
            wf.writeframes(raw_data)
        buf.seek(0)
        buf.name = "audio.wav"

        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=buf,
            language="fr"
        )
        text = transcript.text.strip()
        logger.info(f"Transcription Whisper: '{text}'")
        return text

    except Exception as e:
        logger.error(f"Erreur Whisper: {e}")
        return None


# ─── Réponse LLM ───────────────────────────────────────────────────────────────

def generate_llm_response(question: str, product_context: Optional[str] = None) -> str:
    """
    Génère une réponse via GPT-4o-mini.
    """
    client = get_openai_client()
    if client is None:
        return "Désolé, je ne peux pas répondre pour le moment. Vérifiez la configuration OpenAI."

    # Vérification sécurité
    security = get_security()
    if security:
        try:
            alert = security.check_input(question)
            if alert and alert.triggered and alert.severity.value in ("high", "critical"):
                return "Je ne peux pas répondre à cette question. Je vous invite à consulter le pharmacien."
        except Exception:
            pass

    user_prompt = question.strip()
    if product_context:
        user_prompt = f"Contexte produit: {product_context}\n\nQuestion: {user_prompt}"

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=200,
        )
        answer = response.choices[0].message.content.strip()
        logger.info(f"Réponse LLM: '{answer[:80]}'" if len(answer) > 80 else f"Réponse LLM: '{answer}'")
        return answer
    except Exception as e:
        logger.error(f"Erreur LLM: {e}")
        return "Désolé, une erreur est survenue."


# ─── Identification produit (OpenAI Vision) ─────────────────────────────────────

def identify_product_vision(image_b64: str) -> dict:
    """
    Identifie un produit depuis une image via GPT-4o Vision (OpenAI).
    Retourne un dict avec name, brand, type, hair_type, confidence.
    """
    client = get_openai_client()
    if client is None:
        return {"name": None, "confidence": 0.0, "error": "OpenAI non configuré"}

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": VISION_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_b64}",
                                "detail": "low"
                            }
                        }
                    ]
                }
            ],
            max_tokens=200,
            temperature=0.1,
        )

        raw = response.choices[0].message.content.strip()

        # Extraire le JSON de la réponse
        import re
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
        else:
            result = json.loads(raw)

        logger.info(f"Identification VLM: {result.get('name')} (conf={result.get('confidence', 0):.2f})")
        return result

    except Exception as e:
        logger.error(f"Erreur identification Vision: {e}")
        return {"name": None, "confidence": 0.0, "error": str(e)}


def find_product_by_query(query: str) -> Optional[dict]:
    """Cherche un produit dans la base de données par texte."""
    db = get_database()
    if db is None:
        return None
    try:
        result = db.search_products(query, limit=1)
        if result and len(result) > 0:
            p = result[0]
            return {
                "ean":       getattr(p, "ean", "") or getattr(p, "product_id", ""),
                "name":      getattr(p, "name", ""),
                "brand":     getattr(p, "brand", ""),
                "usage":     getattr(p, "usage", ""),
                "hair_type": getattr(p, "hair_type", ""),
                "price":     getattr(p, "price", 0.0),
            }
    except Exception as e:
        logger.warning(f"Erreur recherche produit: {e}")
    return None


# ─── Serveur Flask ──────────────────────────────────────────────────────────────

app = Flask(__name__)


@app.route("/health", methods=["GET"])
def health():
    """Vérification état du serveur."""
    return jsonify({
        "status":           "ok",
        "openai_available": OPENAI_AVAILABLE and bool(OPENAI_API_KEY),
        "db_available":     get_database() is not None,
        "whisper":          "whisper-1",
        "llm":              "gpt-4o-mini",
        "vision":           "gpt-4o",
    })


@app.route("/google", methods=["POST"])
def transcribe():
    """
    Endpoint de transcription vocale (compatible format Walid).
    Utilise Whisper au lieu de Google SR.

    Body JSON: {"data": "<base64_wav>", "params": "<base64_params>"}
    Réponse:   {"sentence": "<texte transcrit>"}
    """
    req_data = request.get_json(force=True)

    if "data" not in req_data or "params" not in req_data:
        return jsonify({"error": "Champs 'data' et 'params' requis"}), 400

    text = transcribe_whisper(req_data["data"], req_data["params"])
    logger.info(f"Résultat /google: {text}")
    return jsonify({"sentence": text})


@app.route("/ask", methods=["POST"])
def ask():
    """
    Réponse LLM à partir d'une question texte.

    Body JSON: {"question": "<texte>", "product_context": "<contexte optionnel>"}
    Réponse:   {"response": "<réponse>"}
    """
    req_data = request.get_json(force=True)
    question = req_data.get("question", "").strip()

    if not question:
        return jsonify({"error": "Champ 'question' requis"}), 400

    product_context = req_data.get("product_context", "")
    response = generate_llm_response(question, product_context or None)
    return jsonify({"response": response})


@app.route("/process", methods=["POST"])
def process_voice():
    """
    Endpoint combiné : Whisper + réponse LLM en un seul appel.
    Utilisé directement par le box SpeechRecognitionBox.py dans Choregraphe.

    Body JSON: {"data": "<base64_wav>", "params": "<base64_params>"}
    Réponse:   {"sentence": "<transcription>", "response": "<réponse>", "tts": "<texte à dire>"}
    """
    req_data = request.get_json(force=True)

    if "data" not in req_data or "params" not in req_data:
        return jsonify({"error": "Champs 'data' et 'params' requis"}), 400

    # 1. Transcription Whisper
    sentence = transcribe_whisper(req_data["data"], req_data["params"])

    if not sentence:
        msg = "Je n'ai pas bien compris. Pouvez-vous répéter ?"
        return jsonify({"sentence": None, "response": msg, "tts": msg})

    # 2. Réponse LLM
    response = generate_llm_response(sentence)

    return jsonify({
        "sentence": sentence,
        "response": response,
        "tts":      response
    })


@app.route("/identify", methods=["POST"])
def identify_product():
    """
    Identification de produit.
    - Par image (base64 JPEG) → GPT-4o Vision
    - Par texte (query) → base de données

    Body JSON: {"image": "<base64_jpeg>"}
                  ou
               {"query": "<nom produit>"}
    Réponse:   {"product": {...}, "found": true/false}
    """
    req_data = request.get_json(force=True)

    # Identification par image (GPT-4o Vision)
    image_b64 = req_data.get("image", "").strip()
    if image_b64:
        result = identify_product_vision(image_b64)
        name = result.get("name")
        confidence = result.get("confidence", 0.0)

        if name and confidence >= 0.5:
            # Essayer de trouver le produit correspondant en base de données
            db_product = find_product_by_query(name)
            if db_product:
                db_product["confidence"] = confidence
                db_product["source"]     = "vision+db"
                return jsonify({"found": True, "product": db_product})

            # Pas en base de données, mais identifié par la vision
            return jsonify({
                "found": True,
                "product": {
                    "name":      name,
                    "brand":     result.get("brand", ""),
                    "type":      result.get("type", ""),
                    "hair_type": result.get("hair_type", ""),
                    "confidence": confidence,
                    "source":    "vision",
                }
            })

    # Identification par texte
    query = req_data.get("query", "").strip()
    if query:
        product = find_product_by_query(query)
        if product:
            return jsonify({"found": True, "product": product})

    return jsonify({"found": False, "product": None})


@app.route("/products", methods=["GET"])
def list_products():
    """
    Liste des produits pour la tablette.
    Paramètres: ?hair_type=<type>&limit=<n>
    """
    db = get_database()
    if db is None:
        return jsonify({"products": [], "error": "Base de données indisponible"})

    hair_type = request.args.get("hair_type", "").strip()
    limit     = int(request.args.get("limit", "50"))

    try:
        raw = db.search_products(hair_type, limit=limit) if hair_type else db.get_all_products(limit=limit)
        result = []
        for p in (raw or []):
            result.append({
                "ean":       getattr(p, "ean", "") or getattr(p, "product_id", ""),
                "name":      getattr(p, "name", ""),
                "brand":     getattr(p, "brand", ""),
                "price":     getattr(p, "price", 0.0),
                "usage":     getattr(p, "usage", ""),
                "hair_type": getattr(p, "hair_type", ""),
                "image":     getattr(p, "photo_url", "") or "",
            })
        return jsonify({"products": result, "count": len(result)})
    except Exception as e:
        logger.error(f"Erreur liste produits: {e}")
        return jsonify({"products": [], "error": str(e)})


# ─── Serveur WebSocket tablette ─────────────────────────────────────────────────

async def run_tablet_server():
    """Lance le serveur WebSocket pour la tablette."""
    try:
        import websockets

        async def handler(websocket, path=""):
            with _tablet_lock:
                _tablet_clients.add(websocket)
            logger.info(f"Tablette connectée: {websocket.remote_address}")
            try:
                async for message in websocket:
                    try:
                        data = json.loads(message)
                        await handle_tablet_message(websocket, data)
                    except json.JSONDecodeError:
                        pass
            except Exception:
                pass
            finally:
                with _tablet_lock:
                    _tablet_clients.discard(websocket)
                logger.info("Tablette déconnectée")

        async with websockets.serve(
            handler, "0.0.0.0", TABLET_PORT,
            ping_interval=30, ping_timeout=10,
        ):
            logger.info(f"Serveur WebSocket tablette démarré sur ws://0.0.0.0:{TABLET_PORT}")
            await asyncio.Future()

    except ImportError:
        logger.warning("websockets non installé - serveur tablette désactivé")
    except Exception as e:
        logger.error(f"Erreur serveur tablette: {e}")


async def handle_tablet_message(websocket, data: dict):
    """Traite les messages reçus de la tablette."""
    cmd_type = data.get("type", "")
    payload  = data.get("payload", {})

    if cmd_type != "command":
        return

    command = payload.get("command", "") or payload.get("type", "")

    if command == "get_products":
        db = get_database()
        products = []
        if db:
            try:
                hair_type = payload.get("hair_type", "")
                raw = db.search_products(hair_type, limit=50) if hair_type else db.get_all_products(limit=50)
                for p in (raw or []):
                    products.append({
                        "ean":       getattr(p, "ean", "") or getattr(p, "product_id", ""),
                        "name":      getattr(p, "name", ""),
                        "brand":     getattr(p, "brand", ""),
                        "price":     getattr(p, "price", 0.0),
                        "usage":     getattr(p, "usage", ""),
                        "hair_type": getattr(p, "hair_type", ""),
                        "image":     getattr(p, "photo_url", "") or "",
                    })
            except Exception as e:
                logger.warning(f"Erreur get_products: {e}")

        await websocket.send(json.dumps({
            "type":    "products_list",
            "payload": {"products": products}
        }))

    elif command == "ask_question":
        question = payload.get("text", "") or payload.get("question", "")
        if question:
            response = generate_llm_response(question)
            await websocket.send(json.dumps({
                "type":    "qa_answer",
                "payload": {"question": question, "answer": response}
            }))

    elif command == "go_home":
        await websocket.send(json.dumps({
            "type": "show_screen", "payload": {"screen": "home"}
        }))


def start_tablet_thread():
    """Lance le serveur WebSocket tablette dans un thread asyncio dédié."""
    loop = asyncio.new_event_loop()
    def run():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_tablet_server())
    t = threading.Thread(target=run, daemon=True, name="tablet-ws")
    t.start()
    logger.info("Thread serveur tablette démarré")


# ─── Point d'entrée ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Serveur Pepper Parapharmacie (Choregraphe)")
    parser.add_argument("--flask-port",  type=int, default=FLASK_PORT)
    parser.add_argument("--tablet-port", type=int, default=TABLET_PORT)
    parser.add_argument("--no-tablet",   action="store_true")
    args = parser.parse_args()

    logger.info("=== Serveur Pepper Parapharmacie (Choregraphe) ===")
    logger.info(f"Flask API   : http://0.0.0.0:{args.flask_port}")
    logger.info(f"Tablette WS : ws://0.0.0.0:{args.tablet_port}")
    logger.info(f"Transcription : Whisper (whisper-1)")
    logger.info(f"LLM           : GPT-4o-mini")
    logger.info(f"Vision        : GPT-4o")
    logger.info(f"OpenAI        : {'OK' if (OPENAI_AVAILABLE and OPENAI_API_KEY) else 'MANQUANT - renseigner OPENAI_API_KEY dans .env'}")

    get_database()
    get_security()

    if not args.no_tablet:
        start_tablet_thread()

    app.run(host="0.0.0.0", port=args.flask_port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
