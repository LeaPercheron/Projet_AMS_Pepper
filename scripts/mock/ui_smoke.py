#!/usr/bin/env python3
# Smoke test UI tablette (Programme seul)

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Ajouter paths
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tablet"))


async def _run(port: int) -> int:
    # Execute l'action.
    try:
        import websockets
    except Exception:
        print("[SKIP] websockets non installe")
        return 2

    try:
        from server import TabletServer, ServerConfig
    except Exception as e:
        print(f"[ERREUR] Import serveur tablette: {e}")
        return 1

    config = ServerConfig(host="127.0.0.1", port=port, log_level="ERROR")
    server = TabletServer(config)

    task = asyncio.create_task(server.start())
    await asyncio.sleep(0.3)

    uri = f"ws://{config.host}:{config.port}"
    try:
        async with websockets.connect(uri, ping_interval=None) as ws:
            # Attendre message de bienvenue
            try:
                welcome = await asyncio.wait_for(ws.recv(), timeout=2.0)
                print(f"[RECV] {welcome}")
            except asyncio.TimeoutError:
                print("[WARN] Pas de message de bienvenue")

            # Envoyer commande
            command = {
                "type": "command",
                "command": "go_home",
                "data": {}
            }
            await ws.send(json.dumps(command))

            # Demander au serveur d'envoyer un ecran
            await server.send_show_screen(True, "home")

            msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
            print(f"[RECV] {msg}")

    except Exception as e:
        print(f"[FAIL] UI smoke: {e}")
        task.cancel()
        await server.stop()
        return 1

    task.cancel()
    await server.stop()
    print("[OK] UI smoke test termine")
    return 0


def main() -> int:
    # Gere l'action.
    parser = argparse.ArgumentParser(description="Smoke test UI tablette")
    parser.add_argument("--port", type=int, default=8765, help="Port WS")
    args = parser.parse_args()
    return asyncio.run(_run(args.port))


if __name__ == "__main__":
    sys.exit(main())
