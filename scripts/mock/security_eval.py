#!/usr/bin/env python3
# Evaluation securite (Programme seul)

from __future__ import annotations

import sys
from pathlib import Path

# Ajouter src au path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    # Gere l'action.
    try:
        from assistant.safety.security_module import SecurityModule
    except Exception as e:
        print(f"[ERREUR] Import securite: {e}")
        return 1

    blacklist = ROOT / "data" / "blacklist.json"
    security = SecurityModule(blacklist_path=str(blacklist))

    failures = 0

    print("\n[TEST] Textes medicaux")
    test_texts = [
        "J'ai un symptome bizarre, que dois-je prendre ?",
        "Quel traitement pour une migraine ?",
        "C'est sur ordonnance ?",
    ]
    for t in test_texts:
        alert = security.check_text(t)
        status = "OK" if alert.triggered else "FAIL"
        print(f"  [{status}] {t}")
        if not alert.triggered:
            failures += 1

    print("\n[TEST] EAN medicaments")
    test_eans = ["3400930000014", "3400999999999"]
    for ean in test_eans:
        alert = security.check_ean(ean)
        status = "OK" if alert.triggered else "FAIL"
        print(f"  [{status}] {ean}")
        if not alert.triggered:
            failures += 1

    print("\n[TEST] EAN autorises")
    ok_eans = ["3282770149272"]
    for ean in ok_eans:
        alert = security.check_ean(ean)
        status = "OK" if not alert.triggered else "FAIL"
        print(f"  [{status}] {ean}")
        if alert.triggered:
            failures += 1

    if failures == 0:
        print("\n[OK] Securite OK")
        return 0

    print(f"\n[FAIL] {failures} erreurs")
    return 1


if __name__ == "__main__":
    sys.exit(main())
