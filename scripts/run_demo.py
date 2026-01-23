#!/usr/bin/env python3
"""
Demo Interactive
================
Lance une demo interactive de l'assistant en mode simulation.

Usage:
    python scripts/run_demo.py
    python scripts/run_demo.py --verbose
"""

import sys
import argparse
import asyncio
from pathlib import Path

# Ajouter src au path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


async def run_demo(verbose: bool = False):
    """Execute la demo interactive."""
    print("=" * 60)
    print("DEMO ASSISTANT PARAPHARMACIE")
    print("=" * 60)
    print()

    # Importer les modules
    from assistant.config import get_simulation_config
    from assistant.adapters import MockAdapter
    from assistant.adapters.base import LEDColor

    # Configuration simulation
    config = get_simulation_config()
    if verbose:
        config.logging.console_level = "DEBUG"

    # Creer l'adaptateur mock
    adapter = MockAdapter()
    adapter.connect()

    print("Mode: SIMULATION")
    print("Adaptateur: MockAdapter")
    print()

    # Demo des fonctionnalites
    print("[1] Test LEDs")
    colors = [LEDColor.BLUE, LEDColor.GREEN, LEDColor.ORANGE, LEDColor.RED]
    for color in colors:
        adapter.set_led_color(color)
        await asyncio.sleep(0.3)

    print("\n[2] Test TTS")
    adapter.say("Bonjour, je suis votre assistant parapharmacie.")

    print("\n[3] Test presence")
    print(f"  Personne presente: {adapter.is_person_present()}")
    print(f"  Distance: {adapter.get_person_distance()}m")

    print("\n[4] Test gestes")
    adapter.wave()
    adapter.nod()
    adapter.point_at_tablet()

    print("\n[5] Test tablette")
    adapter.show_on_tablet("http://localhost:8765")

    print("\n[6] Statut final")
    status = adapter.get_status()
    for k, v in status.items():
        if isinstance(v, dict):
            print(f"  {k}:")
            for k2, v2 in v.items():
                print(f"    {k2}: {v2}")
        else:
            print(f"  {k}: {v}")

    # Nettoyage
    adapter.disconnect()

    print("\n" + "=" * 60)
    print("DEMO TERMINEE")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Demo assistant parapharmacie")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Mode verbeux")

    args = parser.parse_args()

    try:
        asyncio.run(run_demo(verbose=args.verbose))
        return 0
    except KeyboardInterrupt:
        print("\nInterrompu par l'utilisateur")
        return 0
    except Exception as e:
        print(f"\nErreur: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
