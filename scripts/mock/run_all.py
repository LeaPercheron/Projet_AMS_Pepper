#!/usr/bin/env python3
# Runner Programme seul (B2 -> B7)

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _run(label: str, cmd: list[str]) -> tuple[str, int]:
    # Execute l'action.
    print("\n" + "=" * 70)
    print(f"[RUN] {label}")
    print("=" * 70)
    result = subprocess.run(cmd)
    return label, result.returncode


def main() -> int:
    # Gere l'action.
    parser = argparse.ArgumentParser(description="Run Programme-only tests (B2-B7)")
    parser.add_argument("--report-dir", type=str, default="reports", help="Dossier rapports")
    parser.add_argument("--vision-cases", type=str, default="data/vision_cases", help="Dataset vision")
    parser.add_argument("--audio-input", type=str, default="data/corpus_audio/test_4ch_48k.wav", help="WAV 4ch 48k")
    parser.add_argument("--db", type=str, default="data/products.db", help="DB produits")
    parser.add_argument("--skip-realtime", action="store_true", help="Skip realtime smoke test")
    parser.add_argument("--skip-ui", action="store_true", help="Skip UI smoke test")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    report_dir = root / args.report_dir
    report_dir.mkdir(parents=True, exist_ok=True)

    python = sys.executable
    scripts_dir = Path(__file__).resolve().parent

    tests = [
        ("B2.VisionEval", [python, str(scripts_dir / "vision_eval.py"),
                          "--cases-dir", str(root / args.vision_cases),
                          "--report", str(report_dir / "vision_eval.json")]),
        ("B3.AudioReplay", [python, str(scripts_dir / "audio_replay.py"),
                            "--input", str(root / args.audio_input)]),
        ("B5.DBCheck", [python, str(scripts_dir / "db_check.py"),
                        "--db", str(root / args.db)]),
        ("B6.SecurityEval", [python, str(scripts_dir / "security_eval.py")]),
    ]

    if not args.skip_realtime:
        tests.append(("B4.RealtimeSmoke", [python, str(scripts_dir / "realtime_smoke.py")]))
    if not args.skip_ui:
        tests.append(("B7.UISmoke", [python, str(scripts_dir / "ui_smoke.py")]))

    summary = []
    for label, cmd in tests:
        summary.append(_run(label, cmd))

    print("\n" + "=" * 70)
    print("RESUME")
    print("=" * 70)

    failures = 0
    skipped = 0
    for label, code in summary:
        if code == 0:
            status = "PASS"
        elif code == 2:
            status = "SKIP"
            skipped += 1
        else:
            status = "FAIL"
            failures += 1
        print(f"  [{status}] {label}")

    if failures > 0:
        print(f"\n[FAIL] {failures} test(s) en echec")
        return 1

    if skipped == len(summary):
        print("\n[SKIP] Aucun test execute")
        return 2

    print("\n[OK] Programme-only OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
