#!/usr/bin/env python3
# Réparation TLS Python sur macOS (OpenAI/HuggingFace).

from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path


def _run(cmd):
    print("\n$ " + " ".join(cmd))
    p = subprocess.run(cmd, text=True, capture_output=True)
    if p.stdout:
        print(p.stdout.strip())
    if p.stderr:
        print(p.stderr.strip())
    return p.returncode == 0


def main() -> int:
    if platform.system() != "Darwin":
        print("Ce script est prévu pour macOS.")
        return 1

    py = Path(sys.executable).resolve()
    print(f"Python: {py}")

    ok = True
    ok &= _run([str(py), "-m", "pip", "install", "--upgrade", "pip", "certifi"])

    install_cmd = py.parent.parent / "Resources" / "Install Certificates.command"
    if install_cmd.exists():
        ok &= _run(["/bin/sh", str(install_cmd)])
    else:
        print("Install Certificates.command non trouvé (pas grave si certifi est à jour).")

    # Conseils d'environnement shell pour runtime.
    try:
        import certifi
        ca = certifi.where()
    except Exception:
        ca = ""

    if ca:
        print("\nAjoute ces variables dans ton shell avant lancement:")
        print(f'export SSL_CERT_FILE="{ca}"')
        print(f'export REQUESTS_CA_BUNDLE="{ca}"')
        print(f'export CURL_CA_BUNDLE="{ca}"')
    else:
        print("\ncertifi non disponible après installation.")
        ok = False

    print("\nEnsuite relance:")
    print("PYTHONPATH=src python3 scripts/pepper/preflight_no_robot.py")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
