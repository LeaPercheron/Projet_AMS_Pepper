# Presentation Projet V2 (interne tres detaillee)


## 1) Objectif fonctionnel

Le projet implemente un assistant Pepper en parapharmacie, specialise shampooings.
Trois parcours utilisateur:
1. Identifier un produit (visuel ou code-barres).
2. Lire une fiche produit sur tablette Pepper.
3. Poser une question vocale et obtenir une reponse vocale Pepper.

Parcours complementaire:
- question generale (sans produit scanne): reponse + recommandations produits affichees en cartes.

## 2) Contraintes metier

- Pepper est parfois en reseau contraint (proxy/certificats/captive portal).
- Camera Pepper est faible qualite: besoin de fallback robuste barcode.
- La WebView tablette Pepper est sensible a la compatibilite JS moderne.
- L'utilisateur terrain doit voir des feedbacks clairs (ecrans, LEDs, voix).

## 3) Principes d'architecture

- Degrader proprement plutot que bloquer.
- Prioriser la robustesse terrain sur l'elegance pure.
- Limiter les etats implicites cote tablette (verrous explicites).
- Garder un flux WS simple a deboguer.

## 4) Topologie logique

### 4.1 Processus runtime

Le processus Python `assistant.main` centralise:
- communication Pepper (audio/video/tts/led/tablette)
- logique scan vision + barcode
- logique voix (realtime/fallback)
- routage WebSocket tablette
- synchronisation du contexte produit

### 4.2 Modules et responsabilites

#### `src/assistant/main.py`

Rôle:
- boot sequence
- lifecycle complet
- handlers tablette
- fallbacks de resilence
- pont entre UI, vision, DB, audio, orchestrateur

Points techniques importants:
- `_scan_lock` pour serialiser scans
- `_voice_use_product_context` pour distinguer question produit vs question generale
- `_sync_current_product_context()` pour maintenir le contexte entre modules

#### `src/assistant/adapters/pepper_adapter.py`

Rôle:
- wrapper concret des services NAOqi

Services utilises:
- `ALVideoDevice`
- `ALAudioDevice` / `ALAudioRecorder`
- `ALTextToSpeech`
- `ALLeds`
- `ALTabletService`
- services utilitaires (`ALFileManager`, `ALPythonBridge`)

Particularites:
- fallback audio recorder si service audio principal indisponible
- capture burst camera avec rotation IDs
- freeze/unfreeze tete Pepper pendant scan

#### `src/assistant/vision/vision_module.py`

Rôle:
- pipeline vision complet

Composants:
- classif/identification VLM
- decode barcode multi-variantes image
- arbitrage confiance

Sorties utiles:
- `product` (fiche directe)
- `top3` (confirmation)
- `barcode` (fallback)
- `failed`

#### `src/assistant/database/database_module.py`

Rôle:
- persistance SQLite produits + blacklist

Table centrale:
- `products` (id, ean13, name, brand, category, hair_type, usage, photo_url, etc.)

Acces critiques:
- `get_by_ean()` pour scan barcode
- `get_all_products()` pour UI conseil
- `search_fuzzy()` pour matching textuel

#### `src/assistant/llm/voice_fallback.py`

Rôle:
- pipeline vocal HTTP quand realtime n'est pas utilise

Etapes:
- collecte chunks audio
- detecte/finalise fenetre ecoute
- transcription (OpenAI Whisper HTTP)
- generation reponse texte
- callback TTS Pepper

Mode manuel actuel:
- start listening via bouton
- stop listening via bouton
- pas de timeout court intrusif

#### `tablet/`

UI active:
- `index.html` + `app_legacy_ui.js` + `styles.css`

Pourquoi `app_legacy_ui.js`:
- WebView Pepper plus stable avec syntaxe simple/compatible

Responsabilites front:
- navigation ecrans
- envoi commandes WS
- rendering fiche produit
- rendering recommandations question generale
- verrou `scanInProgress`

#### `tablet/server.py`

Rôle:
- serveur WS
- message broker simple entre UI et handlers backend

Types messages:
- commande entrante `command`
- messages sortants `product_identified`, `barcode_detected`, `qa_answer`, `voice_status`, etc.

`qa_answer` transporte:
- `question`
- `answer`
- `recommendations` (liste produits)
- `context_mode` (`product` ou `general`)

#### `src/assistant/orchestrator/orchestrator.py`

Rôle:
- machine a etats metier
- contexte session/produit/conversation

Utilisation pratique:
- maintain context global
- synchroniser produit courant et historique conversation

## 5) Flux runtime détaillé

### 5.1 Startup

1. lecture env + certifi TLS
2. setup adaptateur
3. setup DB
4. setup securite
5. setup vision
6. setup audio (realtime + fallback HTTP)
7. setup serveur tablette
8. setup orchestrateur
9. setup handlers tablette
10. lancement taches paralleles

### 5.2 Scan visuel detail

Commande: `start_visual_scan`

Sequence:
1. check lock scan
2. UI -> `loading`
3. freeze tete + LED scan + message vocal
4. capture images
5. VLM identify
6. selon resultat:
   - `product_identified`
   - ou `top3_results`
   - ou fallback barcode
7. unfreeze + LED reset

### 5.3 Scan barcode detail

Commande: `start_barcode_scan`

Sequence:
1. UI -> `barcode-scan`
2. freeze tete + LED + message vocal
3. boucle tentatives x frames
4. decode EAN
5. DB lookup
6. success -> `barcode_detected` + `product_identified`
7. echec -> `barcode_failed`
8. unfreeze + reset LEDs

### 5.4 Question vocale detail

Commande start:
- `start_voice_question`

Commande stop:
- `stop_voice_question`

Sequence:
1. `voice_status=listening`
2. capture audio
3. stop -> finalize fenetre
4. `voice_status=processing`
5. transcription
6. requete LLM texte
7. TTS Pepper
8. `qa_answer` + `voice_status=done`

## 6) Contexte produit vs contexte general

Cas A: question depuis fiche produit
- `use_product_context=true`
- la reponse reste associee au produit courant
- UI reste sur fiche produit

Cas B: question generale
- `use_product_context=false`
- contexte produit neutralise
- backend envoie recommandations
- UI affiche reponse + cartes recommandees

## 7) Strategie recommandations

Implementation actuelle:
- heuristic matching local DB
- normalisation texte (accents, ponctuation)
- score tokens + hints metier (pellicules, gras, secs, etc.)
- top N dedup par EAN

Avantages:
- zero dependance externe
- deterministic/debuggable

Limites:
- moins semantique qu'un ranking embeddings
- sensible au vocabulaire utilisateur

## 8) Variables d'environnement essentielles

### Core
- `OPENAI_API_KEY`
- `PEPPER_FORCE_CERTIFI_CA=1`
- `OPENAI_REALTIME_DISABLED=1` (souvent utilise en terrain)

### Vision/scan
- `PEPPER_VLM_DISABLED`
- `PEPPER_VLM_EAGER_LOAD`
- `PEPPER_BARCODE_ATTEMPTS`
- `PEPPER_BARCODE_FRAMES`
- `PEPPER_CAMERA_IDS`
- `PEPPER_CAMERA_DEBUG=1`
- `PEPPER_SCAN_KEEP_IMAGES=1`

### Audio
- `PEPPER_AUDIO_DEBUG=1`
- `PEPPER_AUDIO_RECORDER_FRONT_ONLY=1`
- `PEPPER_AUDIO_RECORDER_PATH`

### UI/WS
- `TABLET_TEXT_QUESTION_ENABLED=0` (par defaut)

## 9) Commandes de lancement (terrain)

### Terminal A
```bash
cd tablet
python3 -m http.server 8080 --bind 0.0.0.0
```

### Terminal B
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

## 10) Diagnostic operationnel

### 10.1 Tablette non affichee
Symptome:
- `showWebview returned False`

Causes probables:
- URL HTTP tablette non joignable depuis Pepper
- reseau Pepper/Mac non routable
- firewall local

### 10.2 Tablette affichee, boutons inactifs
Causes probables:
- WS incorrect (`ws=`)
- WS serveur pas demarre
- cache WebView (oubli `cb=`)

### 10.3 Scan visuel instable
Causes probables:
- VLM indisponible (deps/reseau)
- images floues/sombre
- cadence capture insuffisante

Mitigation:
- fallback barcode automatique
- dump images pour inspection

### 10.4 Barcode ne lit rien
Causes probables:
- angle/luminosite/blur
- EAN non present DB
- `pyzbar/libzbar` non charge

### 10.5 Voix ne repond pas
Causes probables:
- API key absente
- TLS/proxy
- capture micro fallback vide

## 11) Dette technique et axes d'amelioration

1. `main.py` trop volumineux
   - extraire services (scan, voice, reco)

2. deux fronts JS
   - unifier via transpilation cible Pepper

3. reco produits heuristique
   - migrer vers ranking plus semantique

4. test automatique e2e limite
   - renforcer replay audio/camera sans robot

## 12) Roadmap pragmatique

Court terme:
1. stabiliser flux scan/voice terrain
2. renforcer observabilite (logs metriques)
3. durcir protocoles UI contre latence

Moyen terme:
1. refactor services
2. QA automatisee et replay
3. optimisation algo recommandation

Long terme:
1. mode reseau degrade robuste
2. meilleure calibration camera Pepper
3. passage a une doc produit/exploitation complete

## 13) Fichiers a connaitre par coeur

- `src/assistant/main.py`
- `tablet/index.html`
- `tablet/app_legacy_ui.js`
- `tablet/server.py`
- `src/assistant/adapters/pepper_adapter.py`
- `src/assistant/vision/vision_module.py`
- `src/assistant/llm/voice_fallback.py`
- `src/assistant/database/database_module.py`

## 14) Checklist contribution rapide

Avant commit:
1. syntaxe python/js
2. smoke WS local
3. smoke scan barcode
4. smoke voice start/stop
5. verification regression UI produit/question

Commandes utiles:
```bash
python3 -m py_compile src/assistant/main.py tablet/server.py
node --check tablet/app_legacy_ui.js
```
