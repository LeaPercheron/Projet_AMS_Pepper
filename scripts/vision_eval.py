#!/usr/bin/env python3
# Script d'Evaluation Vision

import os
import sys
import json
import time
import argparse
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any
from datetime import datetime

# Ajouter src au path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))


@dataclass
class TestResult:
    # Resultat d'un test unitaire.
    case_name: str
    success: bool

    # Identification
    source: str = ""  # barcode, vlm_high, vlm_medium, vlm_low, failed
    identified_product: str = ""
    expected_product: str = ""
    confidence: float = 0.0

    # Barcode
    barcode_found: bool = False
    barcode_ean: str = ""
    expected_ean: str = ""

    # VLM
    vlm_top1_match: bool = False
    vlm_top3_match: bool = False
    vlm_candidates: List[str] = field(default_factory=list)

    # Metriques
    total_time_ms: float = 0.0
    vlm_time_ms: float = 0.0
    barcode_time_ms: float = 0.0

    # Erreurs
    error: str = ""


@dataclass
class EvalReport:
    # Rapport d'evaluation complet.
    timestamp: str = ""
    total_cases: int = 0

    # Taux de succes
    top1_accuracy: float = 0.0
    top3_accuracy: float = 0.0
    barcode_accuracy: float = 0.0
    overall_success_rate: float = 0.0

    # Par source
    barcode_count: int = 0
    vlm_high_count: int = 0
    vlm_medium_count: int = 0
    vlm_low_count: int = 0
    failed_count: int = 0

    # Temps
    avg_time_ms: float = 0.0
    avg_vlm_time_ms: float = 0.0

    # Details
    results: List[Dict] = field(default_factory=list)

    # Par difficulte
    by_difficulty: Dict[str, Dict] = field(default_factory=dict)


class VisionEvaluator:
    # Evaluateur du pipeline vision.

    def __init__(
        # Initialise l'objet.
        self,
        cases_dir: str = "data/vision_cases",
        use_vlm: bool = False,
        verbose: bool = False
    ):
        self.cases_dir = Path(cases_dir)
        self.use_vlm = use_vlm
        self.verbose = verbose

        # Pipeline vision
        self.vision_pipeline = None
        self.barcode_detector = None

    def setup(self) -> bool:
        # Initialise les modules.
        print("=" * 60)
        print("EVALUATION VISION PIPELINE")
        print("=" * 60)

        try:
            # Importer les modules
            from assistant.vision.vision_module import (
                VisionPipeline, BarcodeDetector, VLMModuleSimulated,
                create_vision_pipeline, CONFIDENCE_HIGH, CONFIDENCE_MEDIUM
            )

            self.CONFIDENCE_HIGH = CONFIDENCE_HIGH
            self.CONFIDENCE_MEDIUM = CONFIDENCE_MEDIUM

            # Charger la base de donnees
            db_path = Path(__file__).parent.parent / "data" / "products.db"

            # Creer le pipeline (simulation par defaut)
            print(f"\n[SETUP] Mode VLM: {'REEL' if self.use_vlm else 'SIMULE'}")

            if self.use_vlm:
                self.vision_pipeline = create_vision_pipeline(
                    use_simulation=False
                )
                if not self.vision_pipeline.load():
                    print("[ERREUR] Impossible de charger le VLM")
                    self.use_vlm = False
                    self.vision_pipeline = create_vision_pipeline(use_simulation=True)
                    self.vision_pipeline.load()
            else:
                self.vision_pipeline = create_vision_pipeline(use_simulation=True)
                self.vision_pipeline.load()

            self.barcode_detector = BarcodeDetector()

            print("[SETUP] Pipeline vision pret")
            return True

        except ImportError as e:
            print(f"[ERREUR] Import impossible: {e}")
            print("[INFO] Utilisation du mode standalone...")
            return self._setup_standalone()

    def _setup_standalone(self) -> bool:
        # Setup minimal sans le module complet.
        try:
            # Test pyzbar seul
            from pyzbar import pyzbar
            print("[SETUP] pyzbar disponible")
            self._pyzbar = pyzbar
            return True
        except ImportError:
            print("[ERREUR] pyzbar non disponible")
            return False

    def discover_cases(self) -> List[Path]:
        # Decouvre les cas de test.
        cases = []

        if not self.cases_dir.exists():
            print(f"[ERREUR] Repertoire non trouve: {self.cases_dir}")
            return cases

        for case_dir in sorted(self.cases_dir.iterdir()):
            if case_dir.is_dir() and not case_dir.name.startswith('.'):
                expected_file = case_dir / "expected.json"
                if expected_file.exists():
                    cases.append(case_dir)

        print(f"\n[DISCOVER] {len(cases)} cas de test trouves")
        return cases

    def load_case(self, case_dir: Path) -> Optional[Dict]:
        # Charge un cas de test.
        expected_file = case_dir / "expected.json"

        try:
            with open(expected_file, 'r', encoding='utf-8') as f:
                expected = json.load(f)

            # Trouver les images
            images = []
            for ext in ['jpg', 'jpeg', 'png']:
                images.extend(sorted(case_dir.glob(f"*.{ext}")))

            return {
                "name": case_dir.name,
                "path": case_dir,
                "expected": expected,
                "images": images
            }

        except Exception as e:
            print(f"[ERREUR] Chargement {case_dir.name}: {e}")
            return None

    def evaluate_case(self, case: Dict) -> TestResult:
        # Evalue un cas de test.
        result = TestResult(
            case_name=case["name"],
            success=False,
            expected_product=case["expected"].get("product_name", ""),
            expected_ean=case["expected"].get("ean13", "")
        )

        start_time = time.time()

        try:
            images = case["images"]
            expected = case["expected"]

            if not images:
                result.error = "Pas d'images dans le cas de test"
                return result

            # Charger les images
            from PIL import Image
            pil_images = []
            for img_path in images[:3]:  # Max 3 frames
                try:
                    img = Image.open(img_path)
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    pil_images.append(img)
                except Exception as e:
                    if self.verbose:
                        print(f"    [WARN] Image {img_path.name}: {e}")

            if not pil_images:
                result.error = "Impossible de charger les images"
                return result

            barcode_start = time.time()
            if self.vision_pipeline and hasattr(self.vision_pipeline, 'barcode_detector'):
                barcode_result = self.vision_pipeline.barcode_detector.detect_in_images(pil_images)
                if barcode_result:
                    result.barcode_found = True
                    result.barcode_ean = barcode_result.ean13
            elif hasattr(self, '_pyzbar'):
                # Mode standalone
                for img in pil_images:
                    try:
                        gray = img.convert('L')
                        barcodes = self._pyzbar.decode(gray)
                        for bc in barcodes:
                            if bc.type == 'EAN13':
                                result.barcode_found = True
                                result.barcode_ean = bc.data.decode('utf-8')
                                break
                    except:
                        pass
                    if result.barcode_found:
                        break

            result.barcode_time_ms = (time.time() - barcode_start) * 1000

            vlm_start = time.time()
            if self.vision_pipeline and hasattr(self.vision_pipeline, 'vlm'):
                # Utiliser le pipeline complet
                identification = self.vision_pipeline.identify_from_images(pil_images)

                result.source = identification.source.value if identification.source else "failed"
                result.identified_product = identification.product_name or ""
                result.confidence = identification.confidence

                # Candidats Top-3
                if identification.candidates:
                    result.vlm_candidates = [c.name for c in identification.candidates]
                elif identification.vlm_result:
                    result.vlm_candidates = [identification.vlm_result.product_name]

                result.vlm_time_ms = identification.vlm_time_ms
            else:
                # Mode sans VLM
                result.source = "barcode" if result.barcode_found else "failed"
                result.vlm_time_ms = 0

            result.vlm_time_ms = (time.time() - vlm_start) * 1000 if result.vlm_time_ms == 0 else result.vlm_time_ms

            # Barcode match
            if result.barcode_found and result.barcode_ean == expected.get("ean13"):
                result.success = True

            # VLM Top-1 match
            expected_top1 = expected.get("expected_top1", "").lower()
            if expected_top1 and result.identified_product:
                if expected_top1 in result.identified_product.lower() or \
                   result.identified_product.lower() in expected_top1:
                    result.vlm_top1_match = True
                    result.success = True

            # VLM Top-3 match
            expected_top3 = [t.lower() for t in expected.get("expected_top3", [])]
            for candidate in result.vlm_candidates:
                candidate_lower = candidate.lower()
                for exp in expected_top3:
                    if exp in candidate_lower or candidate_lower in exp:
                        result.vlm_top3_match = True
                        break

            if result.vlm_top3_match and not result.success:
                # Succes partiel si Top-3 match
                result.success = result.confidence >= self.CONFIDENCE_MEDIUM if hasattr(self, 'CONFIDENCE_MEDIUM') else result.confidence >= 0.6

        except Exception as e:
            result.error = str(e)
            if self.verbose:
                import traceback
                traceback.print_exc()

        result.total_time_ms = (time.time() - start_time) * 1000
        return result

    def run_evaluation(self, case_filter: Optional[str] = None) -> EvalReport:
        # Execute l'evaluation complete.
        report = EvalReport(
            timestamp=datetime.now().isoformat()
        )

        # Decouvrir les cas
        cases = self.discover_cases()
        if case_filter:
            cases = [c for c in cases if case_filter in c.name]

        if not cases:
            print("[ERREUR] Aucun cas de test trouve")
            return report

        report.total_cases = len(cases)

        print(f"\n{'='*60}")
        print(f"EVALUATION DE {len(cases)} CAS")
        print(f"{'='*60}\n")

        # Evaluer chaque cas
        results = []
        for case_dir in cases:
            case = self.load_case(case_dir)
            if not case:
                continue

            print(f"[TEST] {case['name']}...")

            result = self.evaluate_case(case)
            results.append(result)

            # Affichage
            status = "OK" if result.success else "FAIL"
            source = result.source.upper()

            print(f"  [{status}] Source: {source}, Conf: {result.confidence*100:.0f}%")

            if self.verbose:
                print(f"       Identifie: {result.identified_product}")
                print(f"       Attendu: {result.expected_product}")
                print(f"       Barcode: {result.barcode_ean} (trouve: {result.barcode_found})")
                print(f"       Top-1: {result.vlm_top1_match}, Top-3: {result.vlm_top3_match}")
                print(f"       Temps: {result.total_time_ms:.0f}ms")
                if result.error:
                    print(f"       Erreur: {result.error}")
            print()

        # Calculer les metriques
        report.results = [asdict(r) for r in results]

        successful = [r for r in results if r.success]
        report.overall_success_rate = len(successful) / len(results) if results else 0

        # Top-1 / Top-3
        top1_matches = [r for r in results if r.vlm_top1_match]
        top3_matches = [r for r in results if r.vlm_top3_match]
        barcode_matches = [r for r in results if r.barcode_found and r.barcode_ean == r.expected_ean]

        report.top1_accuracy = len(top1_matches) / len(results) if results else 0
        report.top3_accuracy = len(top3_matches) / len(results) if results else 0
        report.barcode_accuracy = len(barcode_matches) / len(results) if results else 0

        # Par source
        for r in results:
            if r.source == "barcode":
                report.barcode_count += 1
            elif r.source == "vlm_high":
                report.vlm_high_count += 1
            elif r.source == "vlm_medium":
                report.vlm_medium_count += 1
            elif r.source == "vlm_low":
                report.vlm_low_count += 1
            else:
                report.failed_count += 1

        # Temps moyens
        if results:
            report.avg_time_ms = sum(r.total_time_ms for r in results) / len(results)
            vlm_times = [r.vlm_time_ms for r in results if r.vlm_time_ms > 0]
            report.avg_vlm_time_ms = sum(vlm_times) / len(vlm_times) if vlm_times else 0

        return report

    def print_report(self, report: EvalReport):
        # Affiche le rapport.
        print("\n" + "=" * 60)
        print("RAPPORT D'EVALUATION")
        print("=" * 60)

        print(f"\nDate: {report.timestamp}")
        print(f"Cas testes: {report.total_cases}")

        print(f"\n--- TAUX DE SUCCES ---")
        print(f"  Global:     {report.overall_success_rate*100:.1f}%")
        print(f"  Top-1 VLM:  {report.top1_accuracy*100:.1f}%")
        print(f"  Top-3 VLM:  {report.top3_accuracy*100:.1f}%")
        print(f"  Barcode:    {report.barcode_accuracy*100:.1f}%")

        print(f"\n--- PAR SOURCE ---")
        print(f"  Barcode:    {report.barcode_count}")
        print(f"  VLM High:   {report.vlm_high_count}")
        print(f"  VLM Medium: {report.vlm_medium_count}")
        print(f"  VLM Low:    {report.vlm_low_count}")
        print(f"  Failed:     {report.failed_count}")

        print(f"\n--- TEMPS ---")
        print(f"  Temps moyen total: {report.avg_time_ms:.0f}ms")
        print(f"  Temps moyen VLM:   {report.avg_vlm_time_ms:.0f}ms")

        print("\n" + "=" * 60)

    def save_report(self, report: EvalReport, output_path: str):
        # Sauvegarde le rapport en JSON.
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        with open(output, 'w', encoding='utf-8') as f:
            json.dump(asdict(report), f, indent=2, ensure_ascii=False)

        print(f"\n[SAVE] Rapport sauvegarde: {output}")


def main():
    # Gere l'action.
    parser = argparse.ArgumentParser(description="Evaluation du pipeline vision")
    parser.add_argument("--case", type=str, help="Filtrer par nom de cas")
    parser.add_argument("--verbose", "-v", action="store_true", help="Affichage detaille")
    parser.add_argument("--use-vlm", action="store_true", help="Utiliser le VLM reel (lent)")
    parser.add_argument("--report", type=str, help="Chemin du rapport JSON")
    parser.add_argument("--cases-dir", type=str, default="data/vision_cases", help="Repertoire des cas")

    args = parser.parse_args()

    # Creer l'evaluateur
    evaluator = VisionEvaluator(
        cases_dir=args.cases_dir,
        use_vlm=args.use_vlm,
        verbose=args.verbose
    )

    # Setup
    if not evaluator.setup():
        print("[ERREUR] Setup echoue")
        sys.exit(1)

    # Evaluation
    report = evaluator.run_evaluation(case_filter=args.case)

    # Afficher
    evaluator.print_report(report)

    # Sauvegarder si demande
    if args.report:
        evaluator.save_report(report, args.report)

    # Code de sortie
    sys.exit(0 if report.overall_success_rate >= 0.5 else 1)


if __name__ == "__main__":
    main()
