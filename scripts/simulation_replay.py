#!/usr/bin/env python3
# Simulation Replay Mode

import os
import sys
import json
import time
import asyncio
import argparse
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any
from datetime import datetime
from enum import Enum

# Ajouter src au path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))


# SCENARIOS

class ScenarioStep(Enum):
    # Types d'etapes de scenario.
    PERSON_DETECTED = "person_detected"
    SPEECH = "speech"
    SHOW_PRODUCT = "show_product"
    VLM_RESULT = "vlm_result"
    BARCODE = "barcode"
    USER_CONFIRM = "user_confirm"
    USER_DENY = "user_deny"
    USER_SELECT = "user_select"
    QUESTION = "question"
    GOODBYE = "goodbye"
    PERSON_LEFT = "person_left"
    WAIT = "wait"
    CHECK_STATE = "check_state"


@dataclass
class Scenario:
    # Definition d'un scenario de test.
    name: str
    description: str
    steps: List[Dict] = field(default_factory=list)
    expected_states: List[str] = field(default_factory=list)
    timeout_s: float = 60.0


# Scenarios predefinis
SCENARIOS = {
    "happy_path": Scenario(
        name="Happy Path",
        description="Parcours ideal: detection -> scan -> info -> question -> fin",
        steps=[
            {"type": "person_detected"},
            {"type": "wait", "duration": 1.0},
            {"type": "check_state", "expected": "GREETING"},
            {"type": "speech", "text": "Bonjour"},
            {"type": "wait", "duration": 0.5},
            {"type": "check_state", "expected": "AWAITING_INTENT"},
            {"type": "show_product"},
            {"type": "wait", "duration": 0.5},
            {"type": "check_state", "expected": "SCANNING_PRODUCT"},
            {"type": "vlm_result", "confidence": 0.92, "product": "Klorane Shampooing"},
            {"type": "wait", "duration": 0.5},
            {"type": "check_state", "expected": "DISPLAYING_INFO"},
            {"type": "question", "text": "Quel est le prix?"},
            {"type": "wait", "duration": 1.0},
            {"type": "goodbye"},
            {"type": "wait", "duration": 0.5},
            {"type": "check_state", "expected": "ENDING"},
            {"type": "person_left"},
            {"type": "wait", "duration": 0.5},
            {"type": "check_state", "expected": "IDLE"},
        ]
    ),

    "top3_confirmation": Scenario(
        name="Top-3 Confirmation",
        description="VLM confiance moyenne -> Top-3 -> selection utilisateur",
        steps=[
            {"type": "person_detected"},
            {"type": "wait", "duration": 0.5},
            {"type": "show_product"},
            {"type": "vlm_result", "confidence": 0.72, "candidates": [
                {"name": "Klorane Camomille", "score": 0.72},
                {"name": "Klorane Avoine", "score": 0.65},
                {"name": "Ducray Extra-Doux", "score": 0.58}
            ]},
            {"type": "wait", "duration": 0.5},
            {"type": "check_state", "expected": "CONFIRMING_TOP3"},
            {"type": "user_select", "index": 0},
            {"type": "wait", "duration": 0.5},
            {"type": "check_state", "expected": "DISPLAYING_INFO"},
            {"type": "goodbye"},
            {"type": "person_left"},
        ]
    ),

    "barcode_fallback": Scenario(
        name="Barcode Fallback",
        description="VLM echoue -> fallback code-barres",
        steps=[
            {"type": "person_detected"},
            {"type": "wait", "duration": 0.5},
            {"type": "show_product"},
            {"type": "vlm_result", "confidence": 0.35, "failed": True},
            {"type": "wait", "duration": 0.5},
            {"type": "check_state", "expected": "SCANNING_BARCODE"},
            {"type": "barcode", "ean": "3282770149272"},
            {"type": "wait", "duration": 0.5},
            {"type": "check_state", "expected": "DISPLAYING_INFO"},
            {"type": "goodbye"},
            {"type": "person_left"},
        ]
    ),

    "timeout_recovery": Scenario(
        name="Timeout Recovery",
        description="Test des timeouts et retour a IDLE",
        steps=[
            {"type": "person_detected"},
            {"type": "wait", "duration": 0.5},
            {"type": "check_state", "expected": "GREETING"},
            # Pas de reponse -> timeout
            {"type": "wait", "duration": 12.0},  # greeting_timeout = 10s
            {"type": "check_state", "expected": "IDLE"},
        ]
    ),

    "security_alert": Scenario(
        name="Security Alert",
        description="Detection question medicale",
        steps=[
            {"type": "person_detected"},
            {"type": "wait", "duration": 0.5},
            {"type": "speech", "text": "Bonjour"},
            {"type": "wait", "duration": 0.5},
            {"type": "question", "text": "Ce shampooing peut-il traiter mon eczema?", "security": True},
            {"type": "wait", "duration": 0.5},
            {"type": "check_state", "expected": "ADVISING"},
            {"type": "wait", "duration": 2.0},
            {"type": "goodbye"},
            {"type": "person_left"},
        ]
    ),
}


# SIMULATEUR

@dataclass
class SimulationResult:
    # Resultat de simulation.
    scenario_name: str
    success: bool
    steps_executed: int
    steps_failed: int
    duration_s: float
    errors: List[str] = field(default_factory=list)
    state_history: List[Dict] = field(default_factory=list)


class ReplaySimulator:
    # Simulateur de replay pour tests deterministes.

    def __init__(self, verbose: bool = False):
        # Initialise l'objet.
        self.verbose = verbose
        self.orchestrator = None
        self.results: List[SimulationResult] = []

    async def setup(self) -> bool:
        # Initialise le simulateur.
        print("=" * 60)
        print("SIMULATION REPLAY")
        print("=" * 60)

        try:
            from assistant.orchestrator.orchestrator import (
                Orchestrator, OrchestratorConfig, State, Event
            )

            # Configuration avec timeouts courts pour les tests
            config = OrchestratorConfig(
                idle_timeout=30.0,
                greeting_timeout=10.0,
                intent_timeout=15.0,
                scan_timeout=10.0,
                confirm_timeout=10.0,
                conversation_timeout=20.0,
                simulation_mode=True,
                log_transitions=self.verbose
            )

            self.orchestrator = Orchestrator(config)
            self.State = State
            self.Event = Event

            print("[SETUP] Orchestrateur initialise")
            return True

        except ImportError as e:
            print(f"[ERREUR] Import: {e}")
            return False

    async def run_scenario(self, scenario: Scenario) -> SimulationResult:
        # Execute un scenario.
        print(f"\n{'='*60}")
        print(f"SCENARIO: {scenario.name}")
        print(f"Description: {scenario.description}")
        print(f"{'='*60}")

        result = SimulationResult(
            scenario_name=scenario.name,
            success=True,
            steps_executed=0,
            steps_failed=0,
            duration_s=0.0
        )

        start_time = time.time()

        # Demarrer l'orchestrateur
        await self.orchestrator.start()

        try:
            for i, step in enumerate(scenario.steps):
                step_type = step.get("type", "")
                print(f"\n[STEP {i+1}] {step_type}")

                success = await self._execute_step(step)

                if success:
                    result.steps_executed += 1
                    if self.verbose:
                        print(f"  OK - Etat actuel: {self.orchestrator.current_state.name}")
                else:
                    result.steps_failed += 1
                    result.success = False
                    error_msg = f"Step {i+1} ({step_type}) failed"
                    result.errors.append(error_msg)
                    print(f"  FAIL - {error_msg}")

                # Enregistrer l'etat
                result.state_history.append({
                    "step": i + 1,
                    "type": step_type,
                    "state": self.orchestrator.current_state.name,
                    "success": success
                })

        except asyncio.TimeoutError:
            result.success = False
            result.errors.append(f"Scenario timeout ({scenario.timeout_s}s)")
        except Exception as e:
            result.success = False
            result.errors.append(f"Exception: {e}")
            if self.verbose:
                import traceback
                traceback.print_exc()

        # Arreter l'orchestrateur
        await self.orchestrator.stop()

        result.duration_s = time.time() - start_time
        return result

    async def _execute_step(self, step: Dict) -> bool:
        # Execute une etape du scenario.
        step_type = step.get("type", "")

        try:
            if step_type == "wait":
                duration = step.get("duration", 1.0)
                await asyncio.sleep(duration)
                return True

            elif step_type == "check_state":
                expected = step.get("expected", "")
                actual = self.orchestrator.current_state.name
                if actual != expected:
                    print(f"    Etat attendu: {expected}, actuel: {actual}")
                return actual == expected

            elif step_type == "person_detected":
                await self.orchestrator.send_event(self.Event.PERSON_DETECTED)
                return True

            elif step_type == "person_left":
                await self.orchestrator.send_event(self.Event.PERSON_LEFT)
                return True

            elif step_type == "speech":
                text = step.get("text", "")
                await self.orchestrator.send_event(
                    self.Event.SPEECH_DETECTED,
                    {"text": text}
                )
                return True

            elif step_type == "show_product":
                await self.orchestrator.send_event(self.Event.PRODUCT_SHOWN)
                return True

            elif step_type == "vlm_result":
                confidence = step.get("confidence", 0.0)
                product = step.get("product", "")
                candidates = step.get("candidates", [])
                failed = step.get("failed", False)

                if failed or confidence < 0.6:
                    await self.orchestrator.send_event(
                        self.Event.VLM_LOW_CONFIDENCE,
                        {"confidence": confidence}
                    )
                elif confidence >= 0.85:
                    await self.orchestrator.send_event(
                        self.Event.VLM_HIGH_CONFIDENCE,
                        {"confidence": confidence, "product_name": product}
                    )
                else:
                    await self.orchestrator.send_event(
                        self.Event.VLM_MEDIUM_CONFIDENCE,
                        {"confidence": confidence, "candidates": candidates}
                    )
                return True

            elif step_type == "barcode":
                ean = step.get("ean", "")
                await self.orchestrator.send_event(
                    self.Event.BARCODE_DETECTED,
                    {"ean": ean}
                )
                return True

            elif step_type == "user_select":
                index = step.get("index", 0)
                await self.orchestrator.send_event(
                    self.Event.USER_SELECTED,
                    {"index": index}
                )
                return True

            elif step_type == "user_confirm":
                await self.orchestrator.send_event(self.Event.USER_CONFIRMED)
                return True

            elif step_type == "user_deny":
                await self.orchestrator.send_event(self.Event.USER_DENIED)
                return True

            elif step_type == "question":
                text = step.get("text", "")
                is_security = step.get("security", False)

                if is_security:
                    await self.orchestrator.send_event(self.Event.SECURITY_ALERT)
                else:
                    await self.orchestrator.send_event(
                        self.Event.QUESTION_ASKED,
                        {"text": text}
                    )
                return True

            elif step_type == "goodbye":
                await self.orchestrator.send_event(self.Event.GOODBYE_DETECTED)
                return True

            else:
                print(f"    Type d'etape inconnu: {step_type}")
                return False

        except Exception as e:
            print(f"    Exception: {e}")
            return False

    async def run_all_scenarios(self) -> bool:
        # Execute tous les scenarios predefinis.
        all_passed = True

        for name, scenario in SCENARIOS.items():
            result = await self.run_scenario(scenario)
            self.results.append(result)

            if not result.success:
                all_passed = False

        return all_passed

    def print_summary(self):
        # Affiche le resume.
        print("\n" + "=" * 60)
        print("RESUME DES SCENARIOS")
        print("=" * 60)

        passed = sum(1 for r in self.results if r.success)
        total = len(self.results)

        print(f"\nScenarios: {passed}/{total} reussis\n")

        for result in self.results:
            status = "PASS" if result.success else "FAIL"
            print(f"[{status}] {result.scenario_name}")
            print(f"       Steps: {result.steps_executed}/{result.steps_executed + result.steps_failed}")
            print(f"       Duree: {result.duration_s:.1f}s")

            if result.errors:
                for error in result.errors:
                    print(f"       Erreur: {error}")

        print("\n" + "=" * 60)


# TEST WEBSOCKET

async def test_websocket():
    # Teste la connexion WebSocket tablette.
    print("=" * 60)
    print("TEST WEBSOCKET TABLETTE")
    print("=" * 60)

    try:
        import websockets

        # Essayer de se connecter au serveur
        uri = "ws://localhost:8765"
        print(f"\n[TEST] Connexion a {uri}...")

        async with websockets.connect(uri, timeout=5) as ws:
            print("[OK] Connecte!")

            # Envoyer un message de test
            test_message = json.dumps({
                "type": "command",
                "command": "ping",
                "timestamp": int(time.time() * 1000)
            })

            print(f"[SEND] {test_message}")
            await ws.send(test_message)

            # Attendre une reponse
            try:
                response = await asyncio.wait_for(ws.recv(), timeout=5.0)
                print(f"[RECV] {response}")
            except asyncio.TimeoutError:
                print("[INFO] Pas de reponse (normal si le serveur n'attend pas de ping)")

            print("\n[OK] Test WebSocket reussi!")

    except ImportError:
        print("[ERREUR] websockets non installe: pip install websockets")
    except ConnectionRefusedError:
        print("[ERREUR] Connexion refusee - le serveur n'est pas demarre")
        print("         Lancez d'abord: python -m assistant.main --simulation")
    except Exception as e:
        print(f"[ERREUR] {e}")


# MAIN

async def main():
    # Gere l'action.
    parser = argparse.ArgumentParser(description="Simulation replay")
    parser.add_argument("--verbose", "-v", action="store_true", help="Affichage detaille")
    parser.add_argument("--scenario", type=str, help="Scenario specifique a executer")
    parser.add_argument("--list-scenarios", action="store_true", help="Lister les scenarios")
    parser.add_argument("--replay-vision", type=str, help="Replay avec cas vision")
    parser.add_argument("--replay-audio", type=str, help="Replay avec fichier audio")
    parser.add_argument("--test-websocket", action="store_true", help="Test connexion WebSocket")

    args = parser.parse_args()

    # Lister les scenarios
    if args.list_scenarios:
        print("\nScenarios disponibles:")
        for name, scenario in SCENARIOS.items():
            print(f"  - {name}: {scenario.description}")
        return

    # Test WebSocket
    if args.test_websocket:
        await test_websocket()
        return

    # Creer le simulateur
    simulator = ReplaySimulator(verbose=args.verbose)

    if not await simulator.setup():
        sys.exit(1)

    # Executer scenario specifique ou tous
    if args.scenario:
        if args.scenario in SCENARIOS:
            result = await simulator.run_scenario(SCENARIOS[args.scenario])
            simulator.results.append(result)
        else:
            print(f"[ERREUR] Scenario inconnu: {args.scenario}")
            print("Utilisez --list-scenarios pour voir les disponibles")
            sys.exit(1)
    else:
        await simulator.run_all_scenarios()

    simulator.print_summary()

    # Code de sortie
    all_passed = all(r.success for r in simulator.results)
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    asyncio.run(main())
