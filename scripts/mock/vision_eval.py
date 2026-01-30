#!/usr/bin/env python3
"""
Wrapper pour l'evaluation vision (Programme seul)
==================================================
Redirige vers scripts/vision_eval.py.

Usage:
    python scripts/mock/vision_eval.py [args...]
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    script = Path(__file__).resolve().parents[1] / "vision_eval.py"
    if not script.exists():
        print(f"[ERREUR] Script introuvable: {script}")
        return 1

    cmd = [sys.executable, str(script)] + sys.argv[1:]
    result = subprocess.run(cmd)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
