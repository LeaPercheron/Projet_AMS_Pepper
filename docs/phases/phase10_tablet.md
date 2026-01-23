# Phase 10 - Interface Tablette

## Objectif

Creer une interface tactile pour la tablette 10.1" de Pepper avec 7 ecrans distincts.

## Ecrans

### 1. Accueil
- Message de bienvenue
- Boutons: [PRODUIT] et [CONSEIL]

### 2. Choix Scan
- Scan visuel vs code-barres
- Instructions illustrees

### 3. Scan Code-Barres
- Animation de scan
- Zone de visee

### 4. Resultats Top-3
- 3 cartes produit avec confiance %
- Selection tactile

### 5. Fiche Produit
- Photo, nom, marque
- Prix, volume
- Usage, benefices
- Ingredients cles

### 6. Conseils Generaux
- Filtre par type de cheveux
- Liste produits scrollable

### 7. Alerte Securite
- Warning visuel
- Message de redirection pharmacien

## Technologies

- **Frontend**: HTML5, CSS3, JavaScript vanilla
- **Backend**: Python WebSocket server
- **Communication**: WebSocket bidirectionnel

## Design

### Principes
- Boutons larges (48px minimum)
- Contraste eleve
- Feedback tactile (animations)
- Lisible a distance

### Palette
- **Primary**: #4A90D9 (Bleu)
- **Success**: #28A745 (Vert)
- **Warning**: #FFC107 (Orange)
- **Error**: #DC3545 (Rouge)

## Protocole WebSocket

### Tablette → Serveur
```json
{"type": "start_scan", "mode": "visual"}
{"type": "confirm_product", "product_id": "..."}
{"type": "select_top3", "index": 1}
```

### Serveur → Tablette
```json
{"type": "product_identified", "product": {...}}
{"type": "top3_results", "products": [...]}
{"type": "security_alert", "message": "..."}
{"type": "screen_change", "screen": "product_card"}
```

## Integration dans la Nouvelle Structure

**Emplacement**: `tablet/`
```
tablet/
├── index.html   # Structure UI
├── styles.css   # Design responsive
├── app.js       # Logique frontend
└── server.py    # Serveur WebSocket
```

**Lancement**:
```bash
# Demarrer le serveur
python tablet/server.py

# Ouvrir dans navigateur
open http://localhost:8765
```

**Integration avec l'assistant**:
```python
from assistant.config import get_config

config = get_config()
# tablet_url = f"http://{config.tablet.ws_host}:{config.tablet.ws_port}"
```
