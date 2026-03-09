# Architecture Systeme (etat actuel)

## But fonctionnel

Le systeme pilote un assistant Pepper pour les shampooings:
- identification produit par scan visuel ou code-barres
- affichage fiche produit sur tablette
- questions vocales avec reponse vocale Pepper
- recommandations produits en mode question generale

## Composants

### Runtime principal
- `src/assistant/main.py`
  - initialise les modules
  - expose les handlers tablette
  - coordonne scan, voix, tablette et contexte

### Adaptateurs robot
- `src/assistant/adapters/pepper_adapter.py`
  - NAOqi direct (services camera/audio/tts/tablette/led)
- `src/assistant/adapters/ssh_bridge_adapter.py`
  - fallback si `qi` indisponible localement
- `src/assistant/adapters/mock_adapter.py`
  - simulation sans robot

### Vision
- `src/assistant/vision/vision_module.py`
  - vision prioritaire OpenAI, fallback VLM (MLX local)
  - detection barcode (`pyzbar`)
  - arbitrage Top-3 prioritaire, puis fallback barcode

### Voix
- `src/assistant/llm/voice_fallback.py`
  - buffering audio micro Pepper
  - transcription HTTP (`whisper-1`) + fallback local
  - reponse texte + callback TTS Pepper

### Donnees
- `src/assistant/database/database_module.py`
  - SQLite produits (`data/products.db`)
  - lookup EAN + recherche fuzzy

### UI tablette
- `tablet/index.html`
- `tablet/app_legacy_ui.js` (script charge en production Pepper)
- `tablet/styles.css`
- `tablet/server.py` (serveur WS)

### Orchestrateur metier
- `src/assistant/orchestrator/orchestrator.py`
  - state machine d'interaction
  - contexte conversation/produit

## Flux principaux

### Flux scan visuel
1. tablette -> `start_visual_scan`
2. backend capture frames camera
3. vision propose un Top-3 pour confirmation utilisateur
4. si confiance visuelle insuffisante -> fallback scan code-barres
5. backend pousse resultat tablette + feedback vocal Pepper

### Flux scan code-barres
1. tablette -> `start_barcode_scan`
2. backend capture burst images
3. decode barcode -> EAN
4. lookup DB par EAN
5. envoi fiche produit a la tablette

### Flux question vocale (fallback HTTP)
1. tablette -> `start_voice_question`
2. utilisateur parle
3. tablette -> `stop_voice_question`
4. transcription audio
5. requete texte OpenAI
6. Pepper parle la reponse
7. tablette affiche reponse (et recommandations en mode general)

## Protocoles I/O

### Tablette -> backend
- `get_products`
- `start_visual_scan`
- `start_barcode_scan`
- `confirm_product`
- `start_voice_question`
- `stop_voice_question`
- `ask_question` (secours texte, desactive par defaut)

### Backend -> tablette
- `show_screen`
- `product_identified`
- `top3_results`
- `barcode_detected`
- `barcode_failed`
- `voice_status`
- `qa_answer`
- `security_alert`
- `error`

## Resilience

- OpenAI Vision indisponible -> fallback VLM local
- vision insuffisante -> fallback barcode
- Realtime indisponible -> HTTP fallback vocal
- anti double-clic scan cote tablette (`scanInProgress`)
- lock temporaire fiche produit pour ignorer ecrasements UI tardifs

## Reseau cible

- Mac (assistant + HTTP tablette + WS tablette)
- Pepper (NAOqi + WebView tablette)
- OpenAI/HuggingFace (si online)

Condition cle:
- Pepper doit pouvoir joindre l'URL `tablet-url` fournie a `assistant.main`.
