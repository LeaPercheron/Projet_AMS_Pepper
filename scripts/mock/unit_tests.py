#!/usr/bin/env python3
# Tests unitaires rapides (Programme seul)

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

# Ajouter src au path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


@dataclass
class TestResult:
    name: str
    passed: bool
    message: str = ""
    skipped: bool = False


def _print_header(title: str) -> None:
    # Gere header.
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def _record(results: List[TestResult], name: str, ok: bool, message: str = "") -> None:
    # Gere l'action.
    results.append(TestResult(name=name, passed=ok, message=message, skipped=False))


def _record_skip(results: List[TestResult], name: str, reason: str) -> None:
    # Gere skip.
    results.append(TestResult(name=name, passed=False, message=reason, skipped=True))


def test_vision_arbitrage(results: List[TestResult]) -> None:
    # Gere vision arbitrage.
    _print_header("B1 - Vision arbitrage")
    try:
        from PIL import Image
        from assistant.vision.vision_module import (
            VisionPipeline,
            BarcodeResult,
            VLMResult,
            IdentificationSource,
            CONFIDENCE_HIGH,
            CONFIDENCE_MEDIUM,
        )
    except Exception as e:
        _record_skip(results, "B1.VisionImport", f"Import impossible: {e}")
        return

    # Base produits minimale
    product_db = {
        "products": [
            {"id": "P1", "ean13": "1111111111111", "name": "Test Shampoo", "brand": "TestBrand"},
            {"id": "P2", "ean13": "2222222222222", "name": "Test Conditioner", "brand": "TestBrand"},
        ]
    }

    # Doubles deterministes
    class DummyBarcodeDetector:
        def __init__(self, result):
            # Initialise l'objet.
            self._result = result

        def detect_in_images(self, images):
            # Gere in images.
            return self._result

    class DummyVLM:
        def __init__(self, confidence: float, name: str, brand: str, top3: Optional[List[VLMResult]] = None):
            # Initialise l'objet.
            self._confidence = confidence
            self._name = name
            self._brand = brand
            self._top3 = top3 or []

        def load_model(self):
            # Charge model.
            return True

        def classify_hair_product(self, image):
            # Gere hair product.
            return True, 0.99

        def identify_product(self, image):
            # Gere product.
            return VLMResult(
                product_name=self._name,
                brand=self._brand,
                confidence=self._confidence,
                product_type="shampooing",
                raw_response="",
                inference_time_ms=1.0,
            )

        def identify_with_top3(self, image):
            # Gere with top3.
            return self._top3

    class DummyCapture:
        def preprocess_for_vlm(self, image):
            # Gere for vlm.
            return image

    images = [Image.new("RGB", (10, 10), color="white") for _ in range(3)]

    # Cas 1: VLM high -> Top-3 (plus d'affichage direct high)
    pipeline = VisionPipeline(product_db, use_simulation=True)
    pipeline.capture = DummyCapture()
    pipeline.vlm = DummyVLM(0.95, "Test Shampoo", "TestBrand")
    pipeline.barcode_detector = DummyBarcodeDetector(
        BarcodeResult(ean13="1111111111111", confidence=0.8, positions=[], image_indices=[0, 1])
    )
    res = pipeline.identify_from_images(images)
    _record(results, "B1.Vision.Top3Priority", res.source == IdentificationSource.VLM_MEDIUM and len(res.candidates) >= 1)

    # Cas 2: VLM medium -> Top-3
    top3 = [
        VLMResult("Test Shampoo", "TestBrand", 0.75, "shampoo", "", 1.0),
        VLMResult("Test Conditioner", "TestBrand", 0.65, "shampoo", "", 1.0),
        VLMResult("Other", "OtherBrand", 0.62, "shampoo", "", 1.0),
    ]
    pipeline = VisionPipeline(product_db, use_simulation=True)
    pipeline.capture = DummyCapture()
    pipeline.vlm = DummyVLM(0.7, "Test Shampoo", "TestBrand", top3=top3)
    pipeline.barcode_detector = DummyBarcodeDetector(None)
    res = pipeline.identify_from_images(images)
    _record(results, "B1.Vision.VLMMedium", res.source == IdentificationSource.VLM_MEDIUM and len(res.candidates) == 3)

    # Cas 3: VLM low + barcode => barcode
    pipeline = VisionPipeline(product_db, use_simulation=True)
    pipeline.capture = DummyCapture()
    pipeline.vlm = DummyVLM(0.4, "Test Shampoo", "TestBrand")
    pipeline.barcode_detector = DummyBarcodeDetector(
        BarcodeResult(ean13="1111111111111", confidence=0.5, positions=[], image_indices=[2])
    )
    res = pipeline.identify_from_images(images)
    _record(results, "B1.Vision.BarcodeFallback", res.source == IdentificationSource.BARCODE)

    # Cas 4: VLM low + pas de barcode => echec
    pipeline = VisionPipeline(product_db, use_simulation=True)
    pipeline.capture = DummyCapture()
    pipeline.vlm = DummyVLM(0.35, "Unknown Product", "UnknownBrand")
    pipeline.barcode_detector = DummyBarcodeDetector(None)
    res = pipeline.identify_from_images(images)
    _record(results, "B1.Vision.LowNoBarcode", res.source == IdentificationSource.FAILED)

    # Seuils
    _record(results, "B1.Vision.Thresholds", CONFIDENCE_HIGH == 0.85 and CONFIDENCE_MEDIUM == 0.60)


def test_security(results: List[TestResult]) -> None:
    # Gere security.
    _print_header("B1 - Securite")
    try:
        from assistant.safety.security_module import SecurityModule
    except Exception as e:
        _record_skip(results, "B1.SecurityImport", f"Import impossible: {e}")
        return

    blacklist = ROOT / "data" / "blacklist.json"
    security = SecurityModule(blacklist_path=str(blacklist))

    alert_text = security.check_text("J'ai des symptomes, quel traitement ?")
    _record(results, "B1.Security.TextMedical", alert_text.triggered)

    alert_ean = security.check_ean("3400930000014")
    _record(results, "B1.Security.EANBlacklist", alert_ean.triggered)

    ok_ean = security.check_ean("3282770149272")
    _record(results, "B1.Security.EANAllowed", not ok_ean.triggered)


def test_state_machine(results: List[TestResult]) -> None:
    # Gere state machine.
    _print_header("B1 - Machine a etats")
    try:
        from assistant.orchestrator.orchestrator import StateMachine, OrchestratorConfig, State, Event
    except Exception as e:
        _record_skip(results, "B1.StateMachineImport", f"Import impossible: {e}")
        return

    sm = StateMachine(OrchestratorConfig(log_transitions=False))

    def _go(event, expected_state):
        # Gere l'action.
        ok = sm.process_event(event)
        return ok and sm.state == expected_state

    ok_path = True
    ok_path &= _go(Event.SPEECH_DETECTED, State.GREETING)
    ok_path &= _go(Event.SPEECH_DETECTED, State.AWAITING_INTENT)
    ok_path &= _go(Event.PRODUCT_SHOWN, State.SCANNING_PRODUCT)
    ok_path &= _go(Event.VLM_MEDIUM_CONFIDENCE, State.CONFIRMING_TOP3)
    ok_path &= _go(Event.USER_SELECTED, State.DISPLAYING_INFO)
    ok_path &= _go(Event.QUESTION_ASKED, State.CONVERSING)
    ok_path &= _go(Event.GOODBYE_DETECTED, State.ENDING)
    ok_path &= _go(Event.TIMEOUT, State.IDLE)
    _record(results, "B1.StateMachine.MainPath", ok_path)

    # Timeout
    sm.reset()
    ok_timeout = sm.process_event(Event.SPEECH_DETECTED) and sm.state == State.GREETING
    ok_timeout &= sm.process_event(Event.TIMEOUT) and sm.state == State.IDLE
    _record(results, "B1.StateMachine.Timeout", ok_timeout)

    # Transition invalide
    sm.reset()
    invalid = sm.process_event(Event.VLM_HIGH_CONFIDENCE)
    _record(results, "B1.StateMachine.Invalid", not invalid and sm.state == State.IDLE)


def main() -> int:
    # Gere l'action.
    results: List[TestResult] = []

    test_vision_arbitrage(results)
    test_security(results)
    test_state_machine(results)

    _print_header("RESUME")
    passed = sum(1 for r in results if r.passed)
    skipped = sum(1 for r in results if r.skipped)
    total = len(results)

    for r in results:
        if r.skipped:
            status = "SKIP"
        else:
            status = "PASS" if r.passed else "FAIL"
        msg = f": {r.message}" if r.message else ""
        print(f"  [{status}] {r.name}{msg}")

    print(f"\nTests: {passed}/{total} passes, {skipped} skippes")

    if passed == 0 and skipped == total:
        return 2
    return 0 if all(r.passed or r.skipped for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
