# Phase 5 - Vision et Identification Produits

## Objectif

Identifier les produits capillaires presentes par le client via:
1. Analyse visuelle par VLM (Vision Language Model)
2. Detection de code-barres EAN-13

## Architecture

```
Images (3 frames)
       │
       ├─→ VLM Classification → Est-ce un produit capillaire?
       │
       ├─→ VLM Identification → Top-3 predictions + confiance
       │
       └─→ Barcode Detection (pyzbar) → EAN-13

Decision Logic:
├─ Barcode 2+ images → Utiliser EAN directement
├─ VLM ≥ 85% → Afficher produit
├─ VLM 60-85% → Afficher Top-3 pour confirmation
├─ VLM < 60% + barcode → Fallback barcode
└─ Echec total → Demander aide manuelle
```

## VLM (Vision Language Model)

### Modele
- **Nom**: mlx-community/Qwen2-VL-2B-Instruct-4bit
- **Plateforme**: Apple Silicon (M4 Pro)
- **Optimisation**: MLX + quantization 4-bit
- **Taille image**: 448x448

### Performances
- Chargement modele: ~3s (premiere fois)
- Classification: ~100ms
- Identification: ~300-400ms
- **Total**: ~500ms par produit

### Prompts VLM
**Classification**:
```
Is this a hair care product (shampoo, conditioner, mask)?
Answer only: yes or no
```

**Identification**:
```
Identify this hair care product.
Return: brand name, product name, estimated confidence 0-100%
```

## Detection Code-Barres

- **Formats**: EAN-13, EAN-8, CODE128
- **Bibliotheque**: pyzbar
- **Latence**: ~50ms
- **Fiabilite**: Requiert 2+ detections identiques

## Seuils de Confiance

| Niveau | Seuil | Action |
|--------|-------|--------|
| HIGH | ≥ 85% | Affichage direct |
| MEDIUM | 60-84% | Top-3 confirmation |
| LOW | < 60% | Fallback barcode |

## Integration dans la Nouvelle Structure

**Emplacement**: `src/assistant/vision/vision_module.py`

**Usage**:
```python
from assistant.vision import VisionModule, VisionConfig

config = VisionConfig(
    vlm_model="mlx-community/Qwen2-VL-2B-Instruct-4bit",
    confidence_high=0.85,
    confidence_medium=0.60
)

vision = VisionModule(config)

# Identifier produit
result = vision.identify_product(images=[frame1, frame2, frame3])

if result.confidence_level == ConfidenceLevel.HIGH:
    display_product(result.top_prediction)
elif result.confidence_level == ConfidenceLevel.MEDIUM:
    show_top3_confirmation(result.predictions)
```

**Tests**:
```bash
python scripts/test_vision.py
python scripts/test_vision.py --image product.jpg
```
