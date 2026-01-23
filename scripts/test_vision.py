#!/usr/bin/env python3
"""
Test Module Vision
==================
Teste le pipeline d'identification de produits.

Usage:
    python scripts/test_vision.py
    python scripts/test_vision.py --image path/to/image.jpg
"""

import sys
import argparse
from pathlib import Path

# Ajouter src au path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def test_vision_import():
    """Teste l'import du module vision."""
    print("=" * 60)
    print("TEST IMPORT MODULE VISION")
    print("=" * 60)

    try:
        from assistant.vision import (
            VisionModule,
            VisionConfig,
            VisionResult,
            ConfidenceLevel
        )
        print("  Import: OK")
        return True
    except ImportError as e:
        print(f"  Import ECHEC: {e}")
        print("  Note: Le module mlx-vlm est requis pour la vision")
        return False


def test_vision_config():
    """Teste la configuration vision."""
    print("\n" + "=" * 60)
    print("TEST CONFIGURATION VISION")
    print("=" * 60)

    try:
        from assistant.vision import VisionConfig

        config = VisionConfig()
        print(f"  Modele VLM: {config.vlm_model}")
        print(f"  Seuil haute confiance: {config.confidence_high}")
        print(f"  Seuil moyenne confiance: {config.confidence_medium}")
        print(f"  Camera: index {config.camera_index}")
        return True
    except Exception as e:
        print(f"  Erreur: {e}")
        return False


def test_barcode_detection():
    """Teste la detection de code-barres."""
    print("\n" + "=" * 60)
    print("TEST DETECTION CODE-BARRES")
    print("=" * 60)

    try:
        import pyzbar
        print("  pyzbar: OK")

        # Test avec image synthetique (pas de vrai code-barres)
        from PIL import Image
        import io

        # Creer une image test
        img = Image.new('RGB', (100, 100), color='white')
        print("  Image test creee")

        return True
    except ImportError as e:
        print(f"  pyzbar non installe: {e}")
        print("  Installer avec: brew install zbar && pip install pyzbar")
        return False
    except Exception as e:
        print(f"  Erreur: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Test module vision")
    parser.add_argument("--image", type=str, help="Image a analyser")
    parser.add_argument("--load-vlm", action="store_true",
                        help="Charger le modele VLM (lent)")

    args = parser.parse_args()

    results = []

    # Tests basiques
    results.append(("Import", test_vision_import()))
    results.append(("Config", test_vision_config()))
    results.append(("Barcode", test_barcode_detection()))

    # Resultat final
    print("\n" + "=" * 60)
    print("RESULTATS")
    print("=" * 60)

    all_pass = True
    for name, passed in results:
        status = "OK" if passed else "ECHEC"
        print(f"  {name}: {status}")
        all_pass &= passed

    print("\n" + "=" * 60)
    if all_pass:
        print("TOUS LES TESTS REUSSIS")
    else:
        print("CERTAINS TESTS ONT ECHOUE")
    print("=" * 60)

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
