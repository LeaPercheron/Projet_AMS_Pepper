# Projet AMS Pepper - Assistant Parapharmacie

Assistant conversationnel pour robot Pepper, specialise sur les produits capillaires (shampooings):
- scan produit (visuel VLM) et scan code-barres (EAN)
- fiche produit sur tablette
- questions vocales au robot + reponse vocale
- mode "question generale" avec recommandations de produits

Ce README decrit l'etat actuel du code et les commandes reelles pour lancer le projet.

## 1) Etat actuel du projet

### Fonctionnel aujourd'hui
- Interface tablette Pepper (`tablet/index.html`)
- WebSocket tablette <-> backend Python
- Scan visuel prioritaire (OpenAI Vision), fallback VLM local (MLX)
- Confirmation visuelle Top-3 prioritaire (pas d'identification directe high)
- Fallback automatique vers scan code-barres si la vision est insuffisante
- Scan code-barres via camera Pepper + pyzbar/libzbar
- Affichage fiche produit (image locale, marque, usage, type cheveux)
- Question vocale depuis tablette
- Reponse vocale Pepper (fallback HTTP OpenAI)
- Question generale: reponse + cartes produits recommandes

### Points importants
- Le vrai ecran principal est `tablet/index.html`.
- `index.html` charge `tablet/app_legacy_ui.js` (choix de compatibilite WebView Pepper).
- Par defaut, le mode question ecrite secours est desactive (`TABLET_TEXT_QUESTION_ENABLED=0`).
- Les timeouts cote tablette sont desactives par defaut (`scan_timeout_ms=0`).

## 2) Architecture resumee

Flux principal:
1. Tablette envoie une commande (`start_visual_scan`, `start_barcode_scan`, `start_voice_question`, etc.)
2. `assistant.main` traite la commande
3. Pepper capture camera/micro via adaptateur
4. Vision/LLM renvoient un resultat
5. Backend pousse l'etat et le resultat a la tablette
6. Pepper annonce vocalement les etapes et la reponse

Dossiers principaux:
- `src/assistant/main.py`: orchestration globale
- `src/assistant/adapters/`: Pepper/SSH bridge/mock
- `src/assistant/vision/`: VLM + barcode
- `src/assistant/database/`: base SQLite produits
- `tablet/`: UI web tablette + serveur WS
- `scripts/pepper/`: diagnostics et preflight

## 3) Prerequis

- macOS + Python 3.10+
- Robot Pepper (NAOqi) pour mode reel
- Cle OpenAI (`OPENAI_API_KEY`) pour voix/question
- Pour scan barcode: `pyzbar` + `libzbar`
- Pour VLM local (Apple Silicon): `mlx`, `mlx-vlm`

## 4) Installation

Depuis la racine du projet:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e .
```

Option VLM local:

```bash
python3 -m pip install -e ".[vlm]"
```

Option utile pour compat tokenizer MLX:

```bash
python3 -m pip install -U "mistral-common[image,hf-hub]>=1.8.8"
```

## 5) Configuration

```bash
cp .env.example .env
```

Variables minimales:

```env
OPENAI_API_KEY=sk-...
PEPPER_IP=192.168.13.213
PEPPER_PORT=9559
TABLET_HOST=0.0.0.0
TABLET_PORT=8765
```

Option recommandee pour forcer un bundle CA propre:

```bash
export PEPPER_FORCE_CERTIFI_CA=1
```

## 6) Lancement du projet (avec Pepper)

### Terminal A - servir la tablette web

```bash
cd tablet
python3 -m http.server 8080 --bind 0.0.0.0
```

### Terminal B - lancer l'assistant

Depuis la racine du projet:

```bash
set -a; source .env; set +a
export OPENAI_REALTIME_DISABLED=1
export PEPPER_FORCE_CERTIFI_CA=1

MY_IP=$(python3 - <<'PY'
import socket
pepper="192.168.13.213"
s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.connect((pepper,9559))
print(s.getsockname()[0])
s.close()
PY
)

PYTHONPATH=src python3 -m assistant.main \
  --pepper-ip 192.168.13.213 \
  --tablet-url "http://${MY_IP}:8080/index.html?ws=ws://${MY_IP}:8765&cb=$(date +%s)"
```

Notes reseau critiques:
- Le Mac qui lance `assistant.main` et Pepper doivent etre routables entre eux.
- Si `showWebview returned False`, l'URL tablette n'est pas joignable depuis Pepper.
- Le parametre `cb=` force le refresh et evite le cache tablette.

## 7) Mini projet test voix (optionnel)

Le sous-projet `voice_test/` sert a isoler la boucle vocale sans scan.

Doc dediee:
- `voice_test/README.md`

## 8) Diagnostics utiles

Diagnostic Pepper (connectivite + tablette):

```bash
PYTHONPATH=src python3 scripts/pepper/pepper_diagnostics.py \
  --pepper-ip 192.168.13.213 \
  --skip-camera --skip-audio-in --skip-audio-out --skip-leds \
  --tablet-url "http://${MY_IP}:8080/index.html"
```

Variables debug scan/camera:

```bash
export PEPPER_BARCODE_DEBUG=1
export PEPPER_CAMERA_DEBUG=1
export PEPPER_SCAN_KEEP_IMAGES=1
```

Dump images scan:
- `logs/pepper_diagnostics/barcode_dump/`

## 9) Problemes frequents

- Tablette affichee mais boutons inactifs:
  - verifier `ws=` dans l'URL
  - verifier que le serveur WS tourne (`ws://<MY_IP>:8765`)
  - forcer cache-buster `&cb=$(date +%s)`

- `showWebview returned False`:
  - URL tablette inaccessible depuis Pepper
  - mauvais reseau, IP Mac incorrecte, firewall

- VLM indisponible:
  - verifier `OPENAI_API_KEY` et acces sortant OpenAI
  - verifier deps `mlx-vlm`, `mistral-common` pour le fallback local
  - fallback barcode reste disponible

- OpenAI ne repond pas:
  - verifier `OPENAI_API_KEY`
  - verifier TLS/certificats (`PEPPER_FORCE_CERTIFI_CA=1`)
  - verifier reseau sortant vers `api.openai.com`

## 10) Commandes courtes (rappel)

Lancer tablette:

```bash
cd tablet && python3 -m http.server 8080 --bind 0.0.0.0
```

Lancer assistant:

```bash
PYTHONPATH=src python3 -m assistant.main --pepper-ip <IP_PEPPER> --tablet-url "http://<IP_MAC>:8080/index.html?ws=ws://<IP_MAC>:8765"
```

## 11) Licence

Projet academique - Master 2 AMS.
