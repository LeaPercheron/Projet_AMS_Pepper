# Phase 6 - Base de Donnees Produits

## Objectif

Gerer une base de donnees SQLite contenant 30+ produits capillaires avec toutes leurs informations, ainsi qu'une blacklist de medicaments.

## Schema Base de Donnees

### Table: products

| Colonne | Type | Description |
|---------|------|-------------|
| id | TEXT (PK) | ID unique (ex: KLORANE-CAMOMILLE-001) |
| ean13 | TEXT (UNIQUE) | Code-barres EAN-13 |
| name | TEXT | Nom du produit |
| brand | TEXT | Marque |
| category | TEXT | Shampooing/Apres-shampooing/Masque |
| hair_type | JSON | Types de cheveux cibles |
| price | REAL | Prix en euros |
| volume | TEXT | Volume (ex: 400ml) |
| usage | TEXT | Frequence d'utilisation |
| instructions | TEXT | Mode d'emploi |
| precautions | JSON | Precautions d'emploi |
| benefits | JSON | Benefices produit |
| key_ingredients | JSON | Ingredients actifs |
| certifications | JSON | Labels (Bio, Vegan, etc.) |
| photo_url | TEXT | URL image produit |
| keywords | JSON | Mots-cles recherche |

### Table: blacklist_ean
- EANs de medicaments a bloquer (100+ entrees)
- Prefixes CIP-13: 340, 3400, 3401

### Table: search_index
- Index full-text pour recherche rapide

## Produits Inclus

**30 produits** de 11 marques:
- Klorane, L'Oreal, Garnier, Rene Furterer
- Ducray, Bioderma, Vichy, Phyto
- La Roche-Posay, Nuxe, Mustela

**Repartition**:
- 25 Shampooings
- 2 Apres-shampooings
- 3 Masques

## Fonctionnalites

### Recherche par EAN
```python
product = db.get_by_ean("3282770149272")
# Latence: < 10ms (indexe)
```

### Recherche Textuelle
```python
results = db.search("shampooing camomille")
# Recherche fuzzy dans nom, marque, keywords
```

### Filtrage
```python
results = db.filter_by(
    category="Shampooing",
    hair_type="cheveux gras",
    brand="Klorane"
)
```

### Verification Blacklist
```python
is_blocked = db.is_blacklisted("3400930000014")  # Doliprane
# True
```

## Integration dans la Nouvelle Structure

**Emplacement**: `src/assistant/database/database_module.py`

**Donnees**: `data/products.db`, `data/blacklist.json`

**Usage**:
```python
from assistant.database import ProductDatabase

db = ProductDatabase("data/products.db")

# Recherche
product = db.get_by_ean("3282770149272")
print(f"{product.name} - {product.price}€")

# Verification blacklist
if db.is_blacklisted(ean):
    raise SecurityAlert("Medicament detecte")
```
