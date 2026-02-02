#!/usr/bin/env python3
# Phase 5 - Module Vision (VLM)

import os
import sys
import time
import asyncio
import tempfile
import struct
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple, Union
from enum import Enum
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
import io

# Constantes
PEPPER_CAMERA_WIDTH = 640
PEPPER_CAMERA_HEIGHT = 480
VLM_TARGET_SIZE = 448  # Taille optimale pour VLM

# Seuils de confiance
CONFIDENCE_HIGH = 0.85  # Affichage direct
CONFIDENCE_MEDIUM = 0.60  # Top-3 avec confirmation
CONFIDENCE_LOW = 0.60  # Fallback code-barres

# Modèle VLM
MODEL_NAME = "mlx-community/Qwen2-VL-2B-Instruct-4bit"

# API PUBLIQUE (COMPAT INTEGRATION)

try:
    from assistant.config import VisionConfig as VisionConfig
except Exception:
    @dataclass
    class VisionConfig:
        # Configuration module vision (fallback si assistant.config absent).
        camera_index: int = 0
        camera_width: int = 640
        camera_height: int = 480
        camera_fps: int = 30
        num_frames: int = 3
        capture_interval_ms: int = 200
        vlm_model: str = MODEL_NAME
        vlm_max_tokens: int = 100
        confidence_high: float = CONFIDENCE_HIGH
        confidence_medium: float = CONFIDENCE_MEDIUM
        confidence_low: float = CONFIDENCE_LOW
        barcode_min_detections: int = 2


class ConfidenceLevel(Enum):
    # Niveau de confiance simplifié pour l'API publique.
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    FAILED = "failed"


@dataclass
class ProductPrediction:
    # Prédiction produit pour l'API publique.
    product_id: Optional[str]
    name: str
    brand: str
    confidence: float
    source: str


@dataclass
class VisionResult:
    # Résultat simplifié pour l'API publique.
    success: bool
    confidence_level: ConfidenceLevel
    top_prediction: Optional[ProductPrediction] = None
    predictions: List[ProductPrediction] = field(default_factory=list)
    message: str = ""
    raw_result: Optional["IdentificationResult"] = None


# STRUCTURES DE DONNÉES

class IdentificationSource(Enum):
    # Source de l'identification.
    BARCODE = "barcode"          # Code-barres détecté
    VLM_HIGH = "vlm_high"        # VLM confiance >= 85%
    VLM_MEDIUM = "vlm_medium"    # VLM confiance 60-85%
    VLM_LOW = "vlm_low"          # VLM confiance < 60%
    FALLBACK = "fallback"        # Fallback code-barres dédié
    FAILED = "failed"            # Échec identification


@dataclass
class BarcodeResult:
    # Résultat de détection code-barres.
    ean13: str
    confidence: float  # Nombre d'images où le code a été trouvé / total
    positions: List[Tuple[int, int, int, int]]  # Bounding boxes
    image_indices: List[int]  # Indices des images où trouvé


@dataclass
class VLMResult:
    # Résultat d'analyse VLM.
    product_name: str
    brand: str
    confidence: float
    product_type: str
    raw_response: str
    inference_time_ms: float


@dataclass
class ProductCandidate:
    # Candidat produit avec score.
    product_id: str
    name: str
    brand: str
    score: float
    source: str  # "vlm" ou "barcode"


@dataclass
class IdentificationResult:
    # Résultat final d'identification.
    success: bool
    source: IdentificationSource
    product_id: Optional[str] = None
    product_name: Optional[str] = None
    brand: Optional[str] = None
    confidence: float = 0.0

    # Top-3 candidats (si VLM_MEDIUM)
    candidates: List[ProductCandidate] = field(default_factory=list)

    # Détails
    barcode_result: Optional[BarcodeResult] = None
    vlm_result: Optional[VLMResult] = None

    # Métriques
    total_time_ms: float = 0.0
    vlm_time_ms: float = 0.0
    barcode_time_ms: float = 0.0

    # Message pour l'utilisateur
    message: str = ""


@dataclass
class CaptureConfig:
    # Configuration de capture.
    num_frames: int = 3
    frame_interval_ms: int = 100  # Intervalle entre frames (rafale)
    use_burst: bool = True  # True = rafale rapide, False = espacé
    resize_to_vlm: bool = True  # Redimensionner à 448x448


# CAPTURE D'IMAGES

class ImageCapture:
    # Capture d'images depuis la caméra Pepper.

    def __init__(self, config: Optional[CaptureConfig] = None):
        # Initialise l'objet.
        self.config = config or CaptureConfig()
        self._naoqi_video = None
        self._subscriber_id = None

    def connect_pepper(self, pepper_ip: str, port: int = 9559) -> bool:
        # Connexion à la caméra Pepper via NAOqi.
        try:
            import qi
            session = qi.Session()
            session.connect(f"tcp://{pepper_ip}:{port}")
            self._naoqi_video = session.service("ALVideoDevice")

            # S'abonner à la caméra (top camera = 0, VGA = 1, RGB = 11)
            self._subscriber_id = self._naoqi_video.subscribeCamera(
                "VisionModule",
                0,  # Top camera
                1,  # VGA (640x480)
                11,  # RGB
                30  # 30 FPS
            )
            print(f"[ImageCapture] Connecté à Pepper {pepper_ip}")
            return True

        except ImportError:
            print("[ImageCapture] NAOqi non disponible - mode simulation")
            return False
        except Exception as e:
            print(f"[ImageCapture] Erreur connexion Pepper: {e}")
            return False

    def capture_frames(self) -> List[Image.Image]:
        # Capture plusieurs frames selon la configuration.
        frames = []

        if self._naoqi_video and self._subscriber_id:
            # Capture depuis Pepper
            frames = self._capture_from_pepper()
        else:
            # Mode simulation - génère des images de test
            print("[ImageCapture] Mode simulation - pas de vraies captures")
            return frames

        return frames

    def _capture_from_pepper(self) -> List[Image.Image]:
        # Capture depuis la caméra Pepper.
        frames = []

        for i in range(self.config.num_frames):
            try:
                # Capturer image
                image_data = self._naoqi_video.getImageRemote(self._subscriber_id)

                if image_data:
                    width = image_data[0]
                    height = image_data[1]
                    array = image_data[6]

                    # Convertir en PIL Image
                    img = Image.frombytes("RGB", (width, height), bytes(array))
                    frames.append(img)

                # Attendre entre les frames
                if i < self.config.num_frames - 1:
                    time.sleep(self.config.frame_interval_ms / 1000.0)

            except Exception as e:
                print(f"[ImageCapture] Erreur capture frame {i}: {e}")

        return frames

    def load_images_from_paths(self, paths: List[str]) -> List[Image.Image]:
        # Charge des images depuis des chemins de fichiers.
        images = []
        for path in paths:
            try:
                img = Image.open(path)
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                images.append(img)
            except Exception as e:
                print(f"[ImageCapture] Erreur chargement {path}: {e}")
        return images

    def preprocess_for_vlm(self, image: Image.Image) -> Image.Image:
        # Prétraite une image pour le VLM.
        # Redimensionner en gardant le ratio puis centrer
        target_size = VLM_TARGET_SIZE

        # Calculer le ratio
        ratio = min(target_size / image.width, target_size / image.height)
        new_size = (int(image.width * ratio), int(image.height * ratio))

        # Redimensionner
        resized = image.resize(new_size, Image.Resampling.LANCZOS)

        # Créer image carrée avec padding noir
        result = Image.new('RGB', (target_size, target_size), (0, 0, 0))
        offset = ((target_size - new_size[0]) // 2, (target_size - new_size[1]) // 2)
        result.paste(resized, offset)

        return result

    def disconnect(self):
        # Déconnexion de Pepper.
        if self._naoqi_video and self._subscriber_id:
            try:
                self._naoqi_video.unsubscribe(self._subscriber_id)
            except:
                pass
            self._naoqi_video = None
            self._subscriber_id = None


# DÉTECTION CODE-BARRES

class BarcodeDetector:
    # Détection de codes-barres avec pyzbar.

    def __init__(self):
        # Initialise l'objet.
        self._pyzbar_available = False
        try:
            from pyzbar import pyzbar
            self._pyzbar = pyzbar
            self._pyzbar_available = True
        except ImportError:
            print("[BarcodeDetector] pyzbar non disponible - pip install pyzbar")

    def detect_in_images(self, images: List[Image.Image]) -> Optional[BarcodeResult]:
        # Détecte les codes-barres dans plusieurs images.
        if not self._pyzbar_available:
            return None

        if not images:
            return None

        # Détecter dans chaque image
        detections: Dict[str, List[Tuple[int, Tuple]]] = {}  # EAN -> [(image_idx, bbox), ...]

        for idx, image in enumerate(images):
            try:
                # Convertir en grayscale pour meilleure détection
                gray = image.convert('L')

                # Détecter codes-barres
                barcodes = self._pyzbar.decode(gray)

                for barcode in barcodes:
                    # Ne garder que les EAN-13
                    if barcode.type == 'EAN13':
                        ean = barcode.data.decode('utf-8')
                        bbox = barcode.rect  # (x, y, w, h)

                        if ean not in detections:
                            detections[ean] = []
                        detections[ean].append((idx, (bbox.left, bbox.top, bbox.width, bbox.height)))

            except Exception as e:
                print(f"[BarcodeDetector] Erreur image {idx}: {e}")

        # Trouver l'EAN le plus fréquent avec validation
        best_ean = None
        best_count = 0

        for ean, occurrences in detections.items():
            if len(occurrences) >= 2 and len(occurrences) > best_count:
                best_ean = ean
                best_count = len(occurrences)

        if best_ean:
            occurrences = detections[best_ean]
            return BarcodeResult(
                ean13=best_ean,
                confidence=len(occurrences) / len(images),
                positions=[occ[1] for occ in occurrences],
                image_indices=[occ[0] for occ in occurrences]
            )

        # Si un seul EAN trouvé dans une seule image, le retourner quand même avec confiance basse
        if detections:
            ean = list(detections.keys())[0]
            occurrences = detections[ean]
            return BarcodeResult(
                ean13=ean,
                confidence=len(occurrences) / len(images),
                positions=[occ[1] for occ in occurrences],
                image_indices=[occ[0] for occ in occurrences]
            )

        return None

    def detect_single(self, image: Image.Image) -> List[str]:
        # Détecte les codes-barres dans une seule image.
        if not self._pyzbar_available:
            return []

        try:
            gray = image.convert('L')
            barcodes = self._pyzbar.decode(gray)
            return [b.data.decode('utf-8') for b in barcodes if b.type == 'EAN13']
        except:
            return []


# MODULE VLM

class VLMModule:
    # Module VLM pour identification visuelle.

    def __init__(self, product_database: Optional[Dict[str, Any]] = None):
        # Initialise l'objet.
        self.model = None
        self.processor = None
        self.config = None
        self.is_loaded = False
        self._load_time_ms = 0

        # Base de produits pour matching
        self.product_database = product_database or {}
        self._product_names = self._build_product_names()

    def _build_product_names(self) -> str:
        # Construit la liste des produits pour le prompt.
        if not self.product_database:
            return ""

        products = self.product_database.get("products", [])
        lines = []
        for p in products:
            lines.append(f"- {p.get('brand', '')} {p.get('name', '')} ({p.get('ean13', '')})")
        return "\n".join(lines)

    def load_model(self) -> bool:
        # Charge le modèle VLM.
        print("[VLM] Chargement du modèle...")
        start_time = time.time()

        try:
            from mlx_vlm import load, generate
            from mlx_vlm.prompt_utils import apply_chat_template
            from mlx_vlm.utils import load_config

            self.model, self.processor = load(MODEL_NAME)
            self.config = load_config(MODEL_NAME)
            self._generate_fn = generate
            self._apply_chat_template = apply_chat_template

            self._load_time_ms = (time.time() - start_time) * 1000
            self.is_loaded = True
            print(f"[VLM] Modèle chargé en {self._load_time_ms:.0f}ms")
            return True

        except ImportError as e:
            print(f"[VLM] mlx-vlm non installé: {e}")
            return False
        except Exception as e:
            print(f"[VLM] Erreur chargement: {e}")
            return False

    def classify_hair_product(self, image: Image.Image) -> Tuple[bool, float]:
        # Classification préalable : est-ce un produit capillaire ?
        if not self.is_loaded:
            return False, 0.0

        prompt = """Regarde cette image et réponds uniquement par OUI ou NON:
Est-ce un produit capillaire (shampooing, après-shampooing, masque, huile, sérum pour cheveux) ?

Réponds au format:
REPONSE: OUI ou NON
CONFIANCE: 0-100"""

        result = self._run_inference(image, prompt, max_tokens=20)

        if result:
            response = result.lower()
            is_hair = "oui" in response and "non" not in response.split("oui")[0]

            # Extraire confiance
            confidence = 0.5
            if "confiance:" in response:
                try:
                    conf_str = response.split("confiance:")[1].strip().split()[0]
                    conf_str = conf_str.replace('%', '')
                    confidence = float(conf_str) / 100.0
                except:
                    pass

            return is_hair, confidence

        return False, 0.0

    def identify_product(self, image: Image.Image) -> VLMResult:
        # Identifie un produit capillaire.
        if not self.is_loaded:
            return VLMResult(
                product_name="",
                brand="",
                confidence=0.0,
                product_type="",
                raw_response="Modèle non chargé",
                inference_time_ms=0
            )

        # Prompt avec liste des produits
        prompt = f"""Tu es un expert en identification de produits capillaires.
Regarde attentivement cette image et LIS LE TEXTE visible sur l'emballage.

PRODUITS CONNUS:
{self._product_names}

INSTRUCTIONS:
1. Identifie la MARQUE sur le flacon
2. Lis le NOM COMPLET du produit
3. Donne ton niveau de confiance

Réponds UNIQUEMENT au format:
PRODUIT: [MARQUE] [Nom du produit]
CONFIANCE: [0-100]
TYPE: [shampooing/apres-shampooing/masque/huile/serum/autre]

Si tu ne peux pas lire le texte, indique CONFIANCE: 0."""

        start_time = time.time()
        result = self._run_inference(image, prompt, max_tokens=50)
        inference_time = (time.time() - start_time) * 1000

        if result:
            return self._parse_identification_response(result, inference_time)

        return VLMResult(
            product_name="",
            brand="",
            confidence=0.0,
            product_type="",
            raw_response="Erreur inférence",
            inference_time_ms=inference_time
        )

    def identify_with_top3(self, image: Image.Image) -> List[VLMResult]:
        # Identifie un produit et retourne Top-3 candidats.
        if not self.is_loaded:
            return []

        prompt = f"""Tu es un expert en identification de produits capillaires.
Regarde cette image et propose les 3 produits les plus probables.

PRODUITS CONNUS:
{self._product_names}

Réponds avec 3 propositions au format:
1. PRODUIT: [nom] | CONFIANCE: [0-100]
2. PRODUIT: [nom] | CONFIANCE: [0-100]
3. PRODUIT: [nom] | CONFIANCE: [0-100]"""

        start_time = time.time()
        result = self._run_inference(image, prompt, max_tokens=100)
        inference_time = (time.time() - start_time) * 1000

        results = []
        if result:
            lines = result.strip().split('\n')
            for line in lines:
                if 'produit:' in line.lower():
                    try:
                        # Parser "1. PRODUIT: xxx | CONFIANCE: 90"
                        parts = line.split('|')
                        if len(parts) >= 2:
                            product_part = parts[0].split(':')[1].strip() if ':' in parts[0] else ""
                            conf_part = parts[1].split(':')[1].strip() if ':' in parts[1] else "0"
                            conf_part = conf_part.replace('%', '').strip()

                            # Extraire marque et nom
                            words = product_part.split()
                            brand = words[0] if words else ""
                            name = ' '.join(words[1:]) if len(words) > 1 else product_part

                            results.append(VLMResult(
                                product_name=product_part,
                                brand=brand,
                                confidence=float(conf_part) / 100.0,
                                product_type="",
                                raw_response=line,
                                inference_time_ms=inference_time / 3
                            ))
                    except:
                        pass

        return results[:3]

    def _run_inference(self, image: Image.Image, prompt: str, max_tokens: int = 50) -> Optional[str]:
        # Exécute une inférence VLM.
        try:
            # Sauvegarder image temporairement
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
                image.save(f, 'JPEG', quality=90)
                temp_path = f.name

            try:
                # Appliquer template
                formatted_prompt = self._apply_chat_template(
                    self.processor,
                    self.config,
                    prompt,
                    num_images=1
                )

                # Générer
                response = self._generate_fn(
                    self.model,
                    self.processor,
                    formatted_prompt,
                    image=[temp_path],
                    max_tokens=max_tokens,
                    verbose=False
                )

                if hasattr(response, 'text'):
                    return response.text
                return str(response)

            finally:
                os.unlink(temp_path)

        except Exception as e:
            print(f"[VLM] Erreur inférence: {e}")
            return None

    def _parse_identification_response(self, response: str, inference_time: float) -> VLMResult:
        # Parse la réponse d'identification.
        product_name = ""
        brand = ""
        confidence = 0.0
        product_type = ""

        lines = response.strip().split('\n')
        for line in lines:
            line_lower = line.lower().strip()

            if line_lower.startswith('produit:'):
                product_name = line.split(':', 1)[1].strip()
                # Extraire marque (premier mot)
                words = product_name.split()
                if words:
                    brand = words[0]

            elif line_lower.startswith('confiance:'):
                try:
                    conf_str = line.split(':', 1)[1].strip()
                    conf_str = conf_str.replace('%', '').strip()
                    confidence = float(conf_str) / 100.0
                    confidence = max(0.0, min(1.0, confidence))
                except:
                    pass

            elif line_lower.startswith('type:'):
                product_type = line.split(':', 1)[1].strip()

        return VLMResult(
            product_name=product_name,
            brand=brand,
            confidence=confidence,
            product_type=product_type,
            raw_response=response,
            inference_time_ms=inference_time
        )


# MODULE VLM SIMULÉ

class VLMModuleSimulated:
    # Version simulée du VLM pour tests.

    def __init__(self, product_database: Optional[Dict[str, Any]] = None):
        # Initialise l'objet.
        self.is_loaded = False
        self.product_database = product_database or {}

        # Produits simulés
        self._simulated = {
            "klorane": ("Klorane Shampooing Illuminateur Camomille", "Klorane", 0.92),
            "elseve": ("L'Oréal Elsève Hyaluron Repulp", "L'Oréal Paris", 0.89),
            "garnier": ("Garnier Ultra Doux Trésors de Miel", "Garnier", 0.91),
            "furterer": ("René Furterer Naturia Micellaire", "René Furterer", 0.93),
            "ducray": ("Ducray Extra-Doux Dermo-Protecteur", "Ducray", 0.90),
        }

    def load_model(self) -> bool:
        # Simule le chargement.
        print("[VLM-SIM] Chargement simulé...")
        time.sleep(0.3)
        self.is_loaded = True
        print("[VLM-SIM] Modèle simulé prêt")
        return True

    def classify_hair_product(self, image: Image.Image) -> Tuple[bool, float]:
        # Simule la classification.
        time.sleep(0.1)
        return True, 0.95

    def identify_product(self, image: Image.Image) -> VLMResult:
        # Simule l'identification.
        import random
        time.sleep(random.uniform(0.2, 0.4))

        # Choisir un produit aléatoire
        key = random.choice(list(self._simulated.keys()))
        name, brand, conf = self._simulated[key]

        # Ajouter variation
        conf += random.uniform(-0.1, 0.1)
        conf = max(0.0, min(1.0, conf))

        return VLMResult(
            product_name=name,
            brand=brand,
            confidence=conf,
            product_type="shampooing",
            raw_response=f"PRODUIT: {name}\nCONFIANCE: {int(conf*100)}%\nTYPE: shampooing",
            inference_time_ms=random.uniform(200, 400)
        )

    def identify_with_top3(self, image: Image.Image) -> List[VLMResult]:
        # Simule Top-3.
        import random
        time.sleep(random.uniform(0.3, 0.5))

        results = []
        keys = list(self._simulated.keys())
        random.shuffle(keys)

        for i, key in enumerate(keys[:3]):
            name, brand, conf = self._simulated[key]
            conf = conf - (i * 0.15) + random.uniform(-0.05, 0.05)
            conf = max(0.0, min(1.0, conf))

            results.append(VLMResult(
                product_name=name,
                brand=brand,
                confidence=conf,
                product_type="shampooing",
                raw_response=f"{i+1}. {name} ({int(conf*100)}%)",
                inference_time_ms=100
            ))

        return results


# PIPELINE COMPLET

class VisionPipeline:
    # Pipeline complet d'identification visuelle.

    def __init__(
        # Initialise l'objet.
        self,
        product_database: Dict[str, Any],
        use_simulation: bool = False
    ):
        self.product_database = product_database
        self.use_simulation = use_simulation

        # Composants
        self.capture = ImageCapture()
        self.barcode_detector = BarcodeDetector()

        if use_simulation:
            self.vlm = VLMModuleSimulated(product_database)
        else:
            self.vlm = VLMModule(product_database)

        # Index EAN -> produit
        self._ean_index = self._build_ean_index()

        # Thread pool pour parallélisation
        self._executor = ThreadPoolExecutor(max_workers=2)

    def _build_ean_index(self) -> Dict[str, Dict]:
        # Construit l'index EAN -> produit.
        index = {}
        for product in self.product_database.get("products", []):
            ean = product.get("ean13")
            if ean:
                index[ean] = product
        return index

    def load(self) -> bool:
        # Charge le modèle VLM.
        return self.vlm.load_model()

    def identify_from_images(self, images: List[Image.Image]) -> IdentificationResult:
        # Identifie un produit à partir de plusieurs images.
        start_time = time.time()

        if not images:
            return IdentificationResult(
                success=False,
                source=IdentificationSource.FAILED,
                message="Aucune image fournie"
            )

        # 1. Détection code-barres en parallèle
        barcode_start = time.time()
        barcode_result = self.barcode_detector.detect_in_images(images)
        barcode_time = (time.time() - barcode_start) * 1000

        # 2. Si code-barres fiable (2+ images), utiliser directement
        if barcode_result and barcode_result.confidence >= 0.66:
            product = self._ean_index.get(barcode_result.ean13)
            if product:
                return IdentificationResult(
                    success=True,
                    source=IdentificationSource.BARCODE,
                    product_id=product.get("id"),
                    product_name=product.get("name"),
                    brand=product.get("brand"),
                    confidence=barcode_result.confidence,
                    barcode_result=barcode_result,
                    total_time_ms=(time.time() - start_time) * 1000,
                    barcode_time_ms=barcode_time,
                    message=f"Produit identifié par code-barres: {product.get('name')}"
                )

        # 3. Classification préalable (produit capillaire ?)
        best_image = images[len(images) // 2]  # Image du milieu
        preprocessed = self.capture.preprocess_for_vlm(best_image)

        is_hair_product, class_conf = self.vlm.classify_hair_product(preprocessed)

        if not is_hair_product:
            return IdentificationResult(
                success=False,
                source=IdentificationSource.FAILED,
                total_time_ms=(time.time() - start_time) * 1000,
                message="Ce n'est pas un produit capillaire. Je ne peux t'aider que pour les produits du rayon cheveux."
            )

        # 4. Identification VLM
        vlm_start = time.time()
        vlm_result = self.vlm.identify_product(preprocessed)
        vlm_time = (time.time() - vlm_start) * 1000

        # 5. Arbitrage selon confiance
        total_time = (time.time() - start_time) * 1000

        # Confiance >= 85% : affichage direct
        if vlm_result.confidence >= CONFIDENCE_HIGH:
            matched_product = self._match_product_by_name(vlm_result.product_name)
            return IdentificationResult(
                success=True,
                source=IdentificationSource.VLM_HIGH,
                product_id=matched_product.get("id") if matched_product else None,
                product_name=vlm_result.product_name,
                brand=vlm_result.brand,
                confidence=vlm_result.confidence,
                vlm_result=vlm_result,
                barcode_result=barcode_result,
                total_time_ms=total_time,
                vlm_time_ms=vlm_time,
                barcode_time_ms=barcode_time,
                message=f"J'ai identifié {vlm_result.product_name} avec une confiance de {vlm_result.confidence*100:.0f}%"
            )

        # Confiance 60-85% : Top-3 avec confirmation
        if vlm_result.confidence >= CONFIDENCE_MEDIUM:
            top3 = self.vlm.identify_with_top3(preprocessed)
            candidates = []

            for vlm_r in top3:
                matched = self._match_product_by_name(vlm_r.product_name)
                candidates.append(ProductCandidate(
                    product_id=matched.get("id") if matched else "",
                    name=vlm_r.product_name,
                    brand=vlm_r.brand,
                    score=vlm_r.confidence,
                    source="vlm"
                ))

            return IdentificationResult(
                success=True,
                source=IdentificationSource.VLM_MEDIUM,
                product_name=vlm_result.product_name,
                brand=vlm_result.brand,
                confidence=vlm_result.confidence,
                candidates=candidates,
                vlm_result=vlm_result,
                barcode_result=barcode_result,
                total_time_ms=total_time,
                vlm_time_ms=vlm_time,
                barcode_time_ms=barcode_time,
                message=f"Je pense qu'il s'agit de {vlm_result.product_name}, mais je ne suis pas sûr. Peux-tu me montrer le code-barres ?"
            )

        # Confiance < 60% : fallback code-barres
        if barcode_result:
            product = self._ean_index.get(barcode_result.ean13)
            if product:
                return IdentificationResult(
                    success=True,
                    source=IdentificationSource.FALLBACK,
                    product_id=product.get("id"),
                    product_name=product.get("name"),
                    brand=product.get("brand"),
                    confidence=barcode_result.confidence,
                    barcode_result=barcode_result,
                    vlm_result=vlm_result,
                    total_time_ms=total_time,
                    vlm_time_ms=vlm_time,
                    barcode_time_ms=barcode_time,
                    message=f"Produit identifié par code-barres: {product.get('name')}"
                )

        # Échec complet
        return IdentificationResult(
            success=False,
            source=IdentificationSource.FAILED,
            vlm_result=vlm_result,
            barcode_result=barcode_result,
            total_time_ms=total_time,
            vlm_time_ms=vlm_time,
            barcode_time_ms=barcode_time,
            message="Je n'ai pas réussi à identifier ce produit. Peux-tu me montrer le code-barres ou l'étiquette plus clairement ?"
        )

    def _match_product_by_name(self, name: str) -> Optional[Dict]:
        # Trouve un produit par son nom (fuzzy matching simple).
        if not name:
            return None

        name_lower = name.lower()
        best_match = None
        best_score = 0

        for product in self.product_database.get("products", []):
            product_name = f"{product.get('brand', '')} {product.get('name', '')}".lower()

            # Score simple basé sur mots communs
            name_words = set(name_lower.split())
            product_words = set(product_name.split())
            common = len(name_words & product_words)
            score = common / max(len(name_words), len(product_words))

            if score > best_score:
                best_score = score
                best_match = product

        return best_match if best_score > 0.3 else None

    def identify_from_paths(self, image_paths: List[str]) -> IdentificationResult:
        # Identifie à partir de chemins d'images.
        images = self.capture.load_images_from_paths(image_paths)
        return self.identify_from_images(images)

    def shutdown(self):
        # Arrête proprement le pipeline.
        self.capture.disconnect()
        self._executor.shutdown(wait=False)


# FACTORY

def create_vision_pipeline(
    # Cree vision pipeline.
    database_path: Optional[str] = None,
    use_simulation: bool = False
) -> VisionPipeline:
    """
    Crée un pipeline de vision.

    Args:
        database_path: Chemin vers la base de données produits (JSON)
        use_simulation: Utiliser le mode simulation

    Returns:
        VisionPipeline configuré
    """
    import json

    # Charger la base de données
    database = {}
    if database_path and os.path.exists(database_path):
        with open(database_path, 'r', encoding='utf-8') as f:
            database = json.load(f)
    else:
        # Utiliser la base mock par défaut
        default_path = Path(__file__).parent.parent / "poc" / "mock_database.json"
        if default_path.exists():
            with open(default_path, 'r', encoding='utf-8') as f:
                database = json.load(f)

    return VisionPipeline(database, use_simulation=use_simulation)


# WRAPPER VISION MODULE (API PUBLIQUE)

class VisionModule:
    # Wrapper public pour intégration avec l'orchestrateur.

    def __init__(
        # Initialise l'objet.
        self,
        config: Optional[VisionConfig] = None,
        database_path: Optional[str] = None,
        use_simulation: Optional[bool] = None
    ):
        self.config = config or VisionConfig()
        self.use_simulation = bool(use_simulation) if use_simulation is not None else False

        # Appliquer les paramètres globaux avant création du pipeline
        self._apply_globals_from_config()

        self.pipeline = create_vision_pipeline(
            database_path=database_path,
            use_simulation=self.use_simulation
        )
        self._apply_capture_config()

    def _apply_globals_from_config(self) -> None:
        # Applique les seuils et le modèle VLM depuis la config.
        global MODEL_NAME, CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, CONFIDENCE_LOW

        if getattr(self.config, "vlm_model", None):
            MODEL_NAME = self.config.vlm_model
        if getattr(self.config, "confidence_high", None) is not None:
            CONFIDENCE_HIGH = self.config.confidence_high
        if getattr(self.config, "confidence_medium", None) is not None:
            CONFIDENCE_MEDIUM = self.config.confidence_medium
        if getattr(self.config, "confidence_low", None) is not None:
            CONFIDENCE_LOW = self.config.confidence_low

    def _apply_capture_config(self) -> None:
        # Configure la capture multi-frames depuis la config.
        capture_cfg = self.pipeline.capture.config
        if getattr(self.config, "num_frames", None) is not None:
            capture_cfg.num_frames = self.config.num_frames
        if getattr(self.config, "capture_interval_ms", None) is not None:
            capture_cfg.frame_interval_ms = self.config.capture_interval_ms

    def load(self) -> bool:
        # Charge le modèle VLM (si nécessaire).
        return self.pipeline.load()

    def identify_product(
        # Gere product.
        self,
        images: Optional[Union[Image.Image, List[Image.Image]]] = None,
        image_paths: Optional[List[str]] = None
    ) -> VisionResult:
        """Identifie un produit à partir d'images ou de chemins."""
        if images is None and not image_paths:
            return VisionResult(
                success=False,
                confidence_level=ConfidenceLevel.FAILED,
                message="Aucune image fournie"
            )

        if isinstance(images, Image.Image):
            images = [images]

        if not self.pipeline.vlm.is_loaded:
            if not self.pipeline.load():
                return VisionResult(
                    success=False,
                    confidence_level=ConfidenceLevel.FAILED,
                    message="Chargement du modèle VLM échoué"
                )

        if image_paths:
            raw_result = self.pipeline.identify_from_paths(image_paths)
        else:
            raw_result = self.pipeline.identify_from_images(images or [])

        return self._to_vision_result(raw_result)

    def shutdown(self) -> None:
        # Arrête proprement le pipeline.
        self.pipeline.shutdown()

    def _to_vision_result(self, result: IdentificationResult) -> VisionResult:
        # Convertit IdentificationResult vers l'API publique.
        if not result.success:
            return VisionResult(
                success=False,
                confidence_level=ConfidenceLevel.FAILED,
                message=result.message,
                raw_result=result
            )

        predictions: List[ProductPrediction] = []

        if result.source == IdentificationSource.VLM_MEDIUM:
            for candidate in result.candidates:
                predictions.append(ProductPrediction(
                    product_id=candidate.product_id or None,
                    name=candidate.name,
                    brand=candidate.brand,
                    confidence=candidate.score,
                    source=candidate.source
                ))
            confidence_level = ConfidenceLevel.MEDIUM
        else:
            predictions.append(ProductPrediction(
                product_id=result.product_id or None,
                name=result.product_name or "",
                brand=result.brand or "",
                confidence=result.confidence,
                source=result.source.value
            ))
            if result.source == IdentificationSource.VLM_HIGH:
                confidence_level = ConfidenceLevel.HIGH
            elif result.source in (IdentificationSource.BARCODE, IdentificationSource.FALLBACK):
                confidence_level = ConfidenceLevel.HIGH
            else:
                confidence_level = ConfidenceLevel.LOW

        top_prediction = predictions[0] if predictions else None

        return VisionResult(
            success=True,
            confidence_level=confidence_level,
            top_prediction=top_prediction,
            predictions=predictions,
            message=result.message,
            raw_result=result
        )


# TEST

if __name__ == "__main__":
    print("=" * 70)
    print("TEST MODULE VISION - PHASE 5")
    print("=" * 70)

    # Créer pipeline en mode simulation
    pipeline = create_vision_pipeline(use_simulation=True)

    # Charger le modèle
    if pipeline.load():
        print("\n[1] TEST IDENTIFICATION SIMULÉE")
        print("-" * 50)

        # Simuler des images (en production, viendraient de Pepper)
        from PIL import Image
        test_images = [Image.new('RGB', (640, 480), color='white') for _ in range(3)]

        result = pipeline.identify_from_images(test_images)

        print(f"  Source: {result.source.value}")
        print(f"  Succès: {result.success}")
        print(f"  Produit: {result.product_name}")
        print(f"  Marque: {result.brand}")
        print(f"  Confiance: {result.confidence*100:.0f}%")
        print(f"  Temps total: {result.total_time_ms:.0f}ms")
        print(f"  Message: {result.message}")

        if result.candidates:
            print(f"\n  Top-3 candidats:")
            for i, c in enumerate(result.candidates, 1):
                print(f"    {i}. {c.name} ({c.score*100:.0f}%)")

        print("\n[2] TEST LOGIQUE D'ARBITRAGE")
        print("-" * 50)

        print(f"  BARCODE priorité: code-barres fiable (2+ images)")
        print(f"  VLM_HIGH: confiance >= {CONFIDENCE_HIGH*100:.0f}%")
        print(f"  VLM_MEDIUM: confiance {CONFIDENCE_MEDIUM*100:.0f}-{CONFIDENCE_HIGH*100:.0f}%")
        print(f"  FALLBACK: confiance < {CONFIDENCE_MEDIUM*100:.0f}% + code-barres")

    pipeline.shutdown()
    print("\n" + "=" * 70)
