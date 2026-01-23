"""
Module Base de Donnees
======================
Gestion des produits capillaires et blacklist.

Usage:
    from assistant.database import ProductDatabase, Product, SearchResult

    db = ProductDatabase("data/products.db")
    product = db.get_by_ean("3282770149272")
    results = db.search_fuzzy("shampooing camomille")
"""

from .database_module import (
    ProductDatabase,
    Product,
    SearchResult,
)

__all__ = [
    "ProductDatabase",
    "Product",
    "SearchResult",
]
