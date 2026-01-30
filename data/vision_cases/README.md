# Dataset Vision - Tests Sans Pepper

Structure pour tester le pipeline vision en mode simulation.

## Organisation

```
vision_cases/
  produit_01_klorane_camomille/
    frame1.jpg          # Vue face avant
    frame2.jpg          # Vue de côté
    frame3.jpg          # Vue avec code-barres visible
    expected.json       # Résultats attendus
  produit_02_elseve_color/
    frame1.jpg
    frame2.jpg
    frame3.jpg
    expected.json
  ...
```

## Format expected.json

```json
{
  "ean13": "3282770149272",
  "product_name": "Klorane Shampooing Illuminateur Camomille",
  "brand": "Klorane",
  "expected_top1": "Klorane Shampooing Camomille",
  "expected_top3": [
    "Klorane Shampooing Camomille",
    "Klorane Shampooing Avoine",
    "Ducray Extra-Doux"
  ],
  "barcode_visible_frames": [3],
  "difficulty": "easy",
  "notes": "Produit bien visible, étiquette lisible"
}
```

## Niveaux de difficulté

- `easy`: Produit bien visible, face avant, bonne lumière
- `medium`: Produit partiellement visible ou de côté
- `hard`: Produit à l'envers, caché, mauvaise lumière
- `barcode_only`: Code-barres seul visible

## Cas de test recommandés

1. **Face avant claire** - Validation baseline
2. **De côté** - Test robustesse VLM
3. **À l'envers** - Fallback vers code-barres
4. **Partiellement caché** - Top-3 confirmation
5. **Code-barres seul** - Priorité EAN
6. **Mauvaise lumière** - Robustesse
7. **Plusieurs produits** - Détection focus

## Exécution des tests

```bash
# Évaluation complète
python scripts/vision_eval.py

# Un seul cas
python scripts/vision_eval.py --case produit_01_klorane

# Rapport détaillé
python scripts/vision_eval.py --verbose --report reports/vision_eval.json
```
