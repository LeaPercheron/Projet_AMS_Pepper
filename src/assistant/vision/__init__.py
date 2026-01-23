"""
Module Vision
=============
Identification de produits par VLM et code-barres.

Usage:
    from assistant.vision import VisionModule, VisionConfig
    from assistant.vision import identify_product

    vision = VisionModule(config)
    result = vision.identify_product(image)
"""

from .vision_module import (
    VisionModule,
    VisionConfig,
    VisionResult,
    ProductPrediction,
    BarcodeResult,
    ConfidenceLevel,
)

__all__ = [
    "VisionModule",
    "VisionConfig",
    "VisionResult",
    "ProductPrediction",
    "BarcodeResult",
    "ConfidenceLevel",
]
