#!/usr/bin/env python3
# Verification DB produits (Programme seul)

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


def main() -> int:
    # Gere l'action.
    parser = argparse.ArgumentParser(description="Check DB produits")
    parser.add_argument("--db", type=str, default="data/products.db", help="Chemin SQLite")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"[ERREUR] DB introuvable: {db_path}")
        return 1

    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    cur.execute("SELECT COUNT(*) as count FROM products")
    total = cur.fetchone()["count"]
    print(f"[INFO] Produits: {total}")

    if total < 30:
        print("[FAIL] Moins de 30 produits")
        return 1

    # Champs essentiels
    cur.execute("""
        SELECT id, ean13, name, brand, category, precautions
        FROM products
    """)
    rows = cur.fetchall()

    missing = 0
    bad_ean = 0
    for r in rows:
        if not r["id"] or not r["ean13"] or not r["name"] or not r["brand"] or not r["category"]:
            missing += 1
        if r["ean13"] and len(str(r["ean13"])) != 13:
            bad_ean += 1

    print(f"[INFO] Lignes avec champs manquants: {missing}")
    print(f"[INFO] EAN invalides: {bad_ean}")

    # Cohérence categories
    cur.execute("SELECT category, COUNT(*) as c FROM products GROUP BY category")
    cats = cur.fetchall()
    print("[INFO] Categories:")
    for c in cats:
        print(f"  - {c['category']}: {c['c']}")

    con.close()

    if missing > 0 or bad_ean > 0:
        print("[FAIL] Integrite DB invalide")
        return 1

    print("[OK] DB OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
