#!/usr/bin/env python3
# Synchronise les images produits en local pour la tablette.

from __future__ import annotations

import argparse
import datetime as dt
import json
import mimetypes
import os
import re
import colorsys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple
from xml.sax.saxutils import escape

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    Image = None
    ImageDraw = None
    ImageFont = None


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _api_urls_for_ean(ean: str) -> Iterable[str]:
    yield f"https://world.openbeautyfacts.org/api/v2/product/{ean}.json"
    yield f"https://world.openfoodfacts.org/api/v2/product/{ean}.json"


def _fetch_json(url: str, timeout_s: float) -> Optional[Dict]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Projet_AMS_Pepper/1.0 (+local image sync)",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8", errors="ignore"))


def _extract_image_url(payload: Dict) -> str:
    product = payload.get("product") or {}
    candidates = [
        product.get("image_front_url"),
        product.get("image_url"),
        product.get("image_front_small_url"),
        product.get("image_small_url"),
    ]

    selected_front = (((product.get("selected_images") or {}).get("front") or {}).get("display") or {})
    if isinstance(selected_front, dict):
        for v in selected_front.values():
            candidates.append(v)

    for value in candidates:
        text = str(value or "").strip()
        if text.startswith("http://") or text.startswith("https://"):
            return text
    return ""


def _guess_extension(url: str, content_type: str) -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct.startswith("image/"):
        if ct == "image/jpeg":
            return ".jpg"
        guessed = mimetypes.guess_extension(ct)
        if guessed:
            return guessed

    parsed = urllib.parse.urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ".jpg"


def _download_image(url: str, dst_prefix: Path, timeout_s: float) -> Optional[Path]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Projet_AMS_Pepper/1.0 (+local image sync)"},
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        content_type = resp.headers.get("Content-Type", "")
        data = resp.read()

    if not data:
        return None

    ext = _guess_extension(url, content_type)
    out_path = dst_prefix.with_suffix(ext)
    out_path.write_bytes(data)
    return out_path


def _placeholder_svg(brand: str, name: str, ean: str) -> str:
    clean_brand = escape((brand or "Shampooing").strip()[:26])
    clean_name = escape((name or "Produit").strip()[:38])
    clean_ean = escape((ean or "").strip())
    initials = "".join([token[:1].upper() for token in re.split(r"\s+", f"{brand} {name}".strip())[:2]]) or "PR"
    initials = escape(initials[:3])

    seed = sum(ord(ch) for ch in f"{brand}|{name}|{ean}")
    hue = abs(seed) % 360
    hue2 = (hue + 28) % 360

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="480" height="480" viewBox="0 0 480 480">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="hsl({hue},56%,42%)"/>
      <stop offset="100%" stop-color="hsl({hue2},58%,32%)"/>
    </linearGradient>
  </defs>
  <rect width="480" height="480" fill="url(#bg)"/>
  <rect x="36" y="36" width="408" height="408" rx="28" fill="rgba(255,255,255,0.92)"/>
  <circle cx="240" cy="175" r="82" fill="hsl({hue},56%,42%)"/>
  <text x="240" y="195" text-anchor="middle" font-family="Segoe UI, Arial, sans-serif" font-size="58" font-weight="700" fill="#ffffff">{initials}</text>
  <text x="240" y="320" text-anchor="middle" font-family="Segoe UI, Arial, sans-serif" font-size="31" font-weight="700" fill="#1f2d3d">{clean_brand}</text>
  <text x="240" y="356" text-anchor="middle" font-family="Segoe UI, Arial, sans-serif" font-size="20" fill="#425466">{clean_name}</text>
  <text x="240" y="392" text-anchor="middle" font-family="Segoe UI, Arial, sans-serif" font-size="16" fill="#6b7c93">{clean_ean}</text>
</svg>
"""


def _write_placeholder(dst_prefix: Path, brand: str, name: str, ean: str) -> Path:
    if Image is None or ImageDraw is None:
        out_path = dst_prefix.with_suffix(".svg")
        out_path.write_text(_placeholder_svg(brand, name, ean), encoding="utf-8")
        return out_path

    text_brand = (brand or "Shampooing").strip()[:26]
    text_name = (name or "Produit").strip()[:34]
    text_ean = (ean or "").strip()[:16]
    initials = "".join([token[:1].upper() for token in re.split(r"\s+", f"{brand} {name}".strip())[:2]]) or "PR"
    seed = sum(ord(ch) for ch in f"{brand}|{name}|{ean}")
    hue = (abs(seed) % 360) / 360.0
    hue2 = ((abs(seed) + 28) % 360) / 360.0
    c1 = colorsys.hls_to_rgb(hue, 0.42, 0.56)
    c2 = colorsys.hls_to_rgb(hue2, 0.32, 0.58)
    rgb1 = tuple(int(v * 255) for v in c1)
    rgb2 = tuple(int(v * 255) for v in c2)

    width, height = 480, 480
    image = Image.new("RGB", (width, height), rgb1)
    draw = ImageDraw.Draw(image)

    # Fond en gradient vertical simple.
    for y in range(height):
        t = y / float(height - 1)
        r = int(rgb1[0] * (1 - t) + rgb2[0] * t)
        g = int(rgb1[1] * (1 - t) + rgb2[1] * t)
        b = int(rgb1[2] * (1 - t) + rgb2[2] * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    panel = (36, 36, 444, 444)
    draw.rounded_rectangle(panel, radius=28, fill=(245, 248, 252))
    draw.ellipse((158, 96, 322, 260), fill=rgb1)

    font = ImageFont.load_default()
    draw.text((240, 175), initials[:3], fill=(255, 255, 255), anchor="mm", font=font)
    draw.text((240, 314), text_brand, fill=(31, 45, 61), anchor="mm", font=font)
    draw.text((240, 346), text_name, fill=(66, 84, 102), anchor="mm", font=font)
    draw.text((240, 378), text_ean, fill=(107, 124, 147), anchor="mm", font=font)

    out_path = dst_prefix.with_suffix(".png")
    image.save(out_path, format="PNG", optimize=True)
    return out_path


def _is_dns_unavailable(err: Exception) -> bool:
    text = str(err).lower()
    return (
        "nodename nor servname provided" in text
        or "name or service not known" in text
        or "temporary failure in name resolution" in text
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Télécharge/synchronise les images shampooings en local.")
    parser.add_argument("--json", default="data/products_export.json", help="Fichier JSON produits.")
    parser.add_argument("--db", default="data/products.db", help="SQLite produits (optionnel).")
    parser.add_argument("--images-dir", default="tablet/product_images", help="Dossier images servi par la tablette.")
    parser.add_argument("--timeout", type=float, default=4.0, help="Timeout HTTP par requête (secondes).")
    parser.add_argument("--offline-only", action="store_true", help="Ne pas tenter le téléchargement réseau.")
    parser.add_argument("--no-db-sync", action="store_true", help="Ne pas resynchroniser SQLite depuis JSON.")
    args = parser.parse_args()

    json_path = (PROJECT_ROOT / args.json).resolve()
    db_path = (PROJECT_ROOT / args.db).resolve()
    images_dir = (PROJECT_ROOT / args.images_dir).resolve()
    images_dir.mkdir(parents=True, exist_ok=True)

    data = json.loads(json_path.read_text(encoding="utf-8"))
    products = data.get("products") or []

    downloaded = 0
    placeholders = 0
    errors = 0
    network_available = not args.offline_only

    for product in products:
        ean = str(product.get("ean13") or "").strip()
        if not ean:
            continue

        brand = str(product.get("brand") or "").strip()
        name = str(product.get("name") or "").strip()
        dst_prefix = images_dir / ean
        local_path: Optional[Path] = None

        if network_available:
            try:
                image_url = ""
                for api_url in _api_urls_for_ean(ean):
                    payload = _fetch_json(api_url, timeout_s=args.timeout)
                    if payload:
                        image_url = _extract_image_url(payload)
                    if image_url:
                        break
                if image_url:
                    local_path = _download_image(image_url, dst_prefix, timeout_s=args.timeout)
                    if local_path:
                        downloaded += 1
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
                if _is_dns_unavailable(e):
                    network_available = False
                errors += 1

        if not local_path:
            local_path = _write_placeholder(dst_prefix, brand=brand, name=name, ean=ean)
            placeholders += 1

        rel = local_path.relative_to(images_dir.parent).as_posix()
        product["photo_url"] = rel

    metadata = data.get("metadata") or {}
    metadata["images_synced_at"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    metadata["images_downloaded"] = downloaded
    metadata["images_placeholders"] = placeholders
    data["metadata"] = metadata
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    db_synced = False
    if not args.no_db_sync and db_path.exists():
        # Import tardif pour éviter l'obligation de PYTHONPATH pendant un dry-run.
        import sys
        sys.path.insert(0, str((PROJECT_ROOT / "src").resolve()))
        from assistant.database import ProductDatabase

        db = ProductDatabase(str(db_path))
        db.import_from_json(str(json_path))
        db_synced = True

    print(
        "[images] Sync terminé:",
        f"downloaded={downloaded}",
        f"placeholders={placeholders}",
        f"errors={errors}",
        f"db_synced={db_synced}",
    )
    print(f"[images] JSON: {json_path}")
    print(f"[images] Dossier images: {images_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
