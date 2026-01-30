#!/usr/bin/env python3
"""
Tests Pepper + Programme (E2E)
==============================
Lance l'assistant et guide des tests d'integration end-to-end.

Usage:
    python scripts/pepper/e2e_integration.py --pepper-ip 192.168.1.100
    python scripts/pepper/e2e_integration.py --pepper-ip 192.168.1.100 --no-launch
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional


@dataclass
class StepResult:
    id: str
    title: str
    status: str  # PASS / FAIL / SKIP
    note: str = ""


def _prompt_step(step_id: str, title: str) -> StepResult:
    print("\n" + "-" * 70)
    print(f"{step_id} - {title}")
    print("Tape: [p]ass, [f]ail, [s]kip, ou un commentaire libre puis Entrée.")
    answer = input("> ").strip()

    if not answer:
        return StepResult(step_id, title, "SKIP", "aucune reponse")

    if answer.lower() in ("p", "pass", "ok", "oui", "y"):
        return StepResult(step_id, title, "PASS")
    if answer.lower() in ("f", "fail", "non", "n"):
        return StepResult(step_id, title, "FAIL")
    if answer.lower() in ("s", "skip"):
        return StepResult(step_id, title, "SKIP")

    # Si commentaire libre, demander ensuite statut
    note = answer
    print("Statut ? [p]ass / [f]ail / [s]kip")
    status = input("> ").strip().lower()
    if status in ("p", "pass", "ok", "oui", "y"):
        return StepResult(step_id, title, "PASS", note)
    if status in ("f", "fail", "non", "n"):
        return StepResult(step_id, title, "FAIL", note)
    return StepResult(step_id, title, "SKIP", note)


def _start_assistant(pepper_ip: str, extra_args: List[str]) -> subprocess.Popen:
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    src_path = str(root / "src")
    env["PYTHONPATH"] = src_path + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

    cmd = [sys.executable, "-m", "assistant.main", "--pepper-ip", pepper_ip] + extra_args
    print("\n[START] " + " ".join(cmd))
    return subprocess.Popen(cmd, cwd=str(root), env=env)


def _stop_assistant(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=10)
    except Exception:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description="Tests Pepper + Programme (E2E)")
    parser.add_argument("--pepper-ip", required=True, help="IP du robot Pepper")
    parser.add_argument("--no-launch", action="store_true", help="N'essaie pas de lancer assistant.main")
    parser.add_argument("--assistant-arg", action="append", default=[], help="Args additionnels pour assistant.main")
    parser.add_argument("--report", type=str, default="reports/pepper_e2e.json", help="Chemin du rapport JSON")
    args = parser.parse_args()

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    assistant_proc: Optional[subprocess.Popen] = None
    if not args.no_launch:
        assistant_proc = _start_assistant(args.pepper_ip, args.assistant_arg)
        print("[INFO] Attendez le demarrage complet (modules charges)...")
        time.sleep(8)
    else:
        print("[INFO] Assistant deja lance (no-launch)")

    results: List[StepResult] = []

    print("\n" + "=" * 70)
    print("C1 - Smoke test integration (5 min)")
    print("=" * 70)
    print("Verifier le cycle minimal: accueil -> scan -> fiche (sans crash).")

    results.append(_prompt_step("C1.1", "Tablette affiche accueil + message info (RGPD)"))
    results.append(_prompt_step("C1.2", "LEDs changent selon etat (ecoute/analyse/alerte)"))
    results.append(_prompt_step("C1.3", "Capture camera: 3 images prises"))
    results.append(_prompt_step("C1.4", "Scan: VLM + EAN (arbitrage OK)"))
    results.append(_prompt_step("C1.5", "Lecture audio Pepper via streaming bas niveau"))

    print("\n" + "=" * 70)
    print("C2 - Scenarios coeur produit")
    print("=" * 70)
    results.append(_prompt_step("C2.1", "Produit bien visible -> identification directe"))
    results.append(_prompt_step("C2.2", "Produit a l'envers -> Top-3 ou barcode"))
    results.append(_prompt_step("C2.3", "Produit hors rayon capillaire -> refus"))
    results.append(_prompt_step("C2.4", "Echec VLM + EAN -> scan barcode dedie puis 'pas dans base'"))

    print("\n" + "=" * 70)
    print("C3 - Scenarios securite (bloquants)")
    print("=" * 70)
    results.append(_prompt_step("C3.1", "Medicament detecte -> alerte orange + redirection"))
    results.append(_prompt_step("C3.2", "Question medicale -> filtre mots-cles + reponse securite"))

    print("\n" + "=" * 70)
    print("C4 - Dialogue et demi-duplex")
    print("=" * 70)
    results.append(_prompt_step("C4.1", "Parole utilisateur pendant Pepper -> input ignore (zeros/loggable)"))
    results.append(_prompt_step("C4.2", "Hesitations 'euh...' -> pas coupe trop tot"))

    # Stop assistant if launched
    if assistant_proc is not None:
        _stop_assistant(assistant_proc)

    # Resume
    passed = sum(1 for r in results if r.status == "PASS")
    failed = sum(1 for r in results if r.status == "FAIL")
    skipped = sum(1 for r in results if r.status == "SKIP")

    print("\n" + "=" * 70)
    print("RESUME")
    print("=" * 70)
    for r in results:
        note = f" - {r.note}" if r.note else ""
        print(f"  [{r.status}] {r.id}: {r.title}{note}")
    print(f"\nPASS={passed} FAIL={failed} SKIP={skipped}")

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in results], f, indent=2, ensure_ascii=False)
    print(f"[SAVE] Rapport: {report_path}")

    if failed > 0:
        return 1
    if passed == 0 and skipped == len(results):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
