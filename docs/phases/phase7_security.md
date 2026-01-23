# Phase 7 - Module Securite

## Objectif

Implementer des filtres de securite pour:
1. Detecter les questions medicales inappropriees
2. Bloquer les codes-barres de medicaments
3. Refuser les usages dangereux

## Architecture

```
Input (texte ou EAN)
       │
       ├─→ EAN Blacklist Check → Medicament detecte?
       │
       ├─→ Medical Keywords Filter → 80+ termes medicaux
       │
       ├─→ Dangerous Usage Filter → Ingestion, yeux, enfants
       │
       └─→ Animal Usage Check → Usage animal detecte?

Output: SecurityAlert {
    triggered: bool,
    alert_type: AlertType,
    severity: Severity,
    matched_keywords: [],
    response: str,
    robot_action: str
}
```

## 4 Scenarios Obligatoires

| Scenario | Trigger | Reponse |
|----------|---------|---------|
| Ingestion | "Peut-on boire le shampooing?" | Refus + redirection pharmacien |
| Usage animal | "Pour mon chien?" | Produit humain uniquement |
| Condition medicale | "Perte cheveux tension?" | Refus medical |
| Medicament | EAN Doliprane | Detection + LED orange |

## Filtres

### Mots-cles Medicaux (80+)
- **Symptomes**: douleur, mal, demangeaison, fievre
- **Conditions**: allergie, eczema, psoriasis, infection
- **Termes medicaux**: traitement, medicament, ordonnance
- **Actions**: consulter, medecin, dermatologue, urgence

### Blacklist EAN
- 100+ medicaments (Doliprane, Advil, Nurofen, etc.)
- Prefixes CIP-13 francais

### Usages Dangereux
- Ingestion/boire
- Contact yeux
- Usage enfants < 3 ans
- Grossesse/allaitement sans avis

## Niveaux de Severite

| Niveau | Action |
|--------|--------|
| LOW | Log + continuer |
| MEDIUM | Avertissement vocal |
| HIGH | Refus + redirection pharmacien |
| CRITICAL | Blocage total + LED rouge |

## Performances

- **Latence filtre texte**: 0.024ms (cible < 1ms)
- **Latence check EAN**: < 0.1ms
- **Taux faux-negatifs**: < 0.1%

## Integration dans la Nouvelle Structure

**Emplacement**: `src/assistant/safety/security_module.py`

**Usage**:
```python
from assistant.safety import SecurityModule, SecurityConfig

security = SecurityModule(SecurityConfig(
    latency_target_ms=1.0,
    strict_mode=True
))

# Verifier texte
alert = security.check_text("puis-je boire ce shampooing?")
if alert.triggered:
    print(f"ALERTE: {alert.alert_type}")
    print(f"Reponse: {alert.response}")

# Verifier EAN
alert = security.check_ean("3400930000014")
if alert.triggered:
    # Medicament detecte
    set_led_color(LEDColor.ORANGE)
```
