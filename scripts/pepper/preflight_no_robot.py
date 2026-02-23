#!/usr/bin/env python3
# Preflight sans robot: vérifie voix/API, VLM et scan barcode côté laptop.

from __future__ import annotations

import importlib.util
import os
import socket
import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[2]


@dataclass
class CheckResult:
    name: str
    status: str  # PASS | WARN | FAIL
    detail: str


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    load_dotenv(ROOT / ".env")
    load_dotenv()


def _configure_tls_ca_bundle() -> Optional[str]:
    force = (os.getenv("PEPPER_FORCE_CERTIFI_CA", "1") or "").strip().lower() in {"1", "true", "yes", "on"}
    if not force:
        return None
    try:
        import certifi
        ca_path = certifi.where()
    except Exception:
        return None
    if not ca_path or not Path(ca_path).exists():
        return None
    os.environ.setdefault("SSL_CERT_FILE", ca_path)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", ca_path)
    os.environ.setdefault("CURL_CA_BUNDLE", ca_path)
    return ca_path


def _has_module(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _safe(check_name: str, fn: Callable[[], CheckResult]) -> CheckResult:
    try:
        return fn()
    except Exception as e:
        return CheckResult(check_name, "FAIL", f"Exception: {e}")


def check_openai_key() -> CheckResult:
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        return CheckResult("OPENAI key", "FAIL", "OPENAI_API_KEY absent")
    lowered = key.lower()
    if lowered in {"ta_cle", "your_key", "change_me"} or "xxxx" in lowered:
        return CheckResult("OPENAI key", "FAIL", "OPENAI_API_KEY semble placeholder")
    return CheckResult("OPENAI key", "PASS", "clé présente")


def check_ca_bundle() -> CheckResult:
    ca = (os.getenv("SSL_CERT_FILE") or "").strip()
    if ca and Path(ca).exists():
        return CheckResult("CA bundle Python", "PASS", f"SSL_CERT_FILE={ca}")
    return CheckResult("CA bundle Python", "WARN", "SSL_CERT_FILE non défini")


def _dns_lookup(host: str) -> Tuple[bool, str]:
    try:
        ip = socket.gethostbyname(host)
        return True, ip
    except Exception as e:
        return False, str(e)


def _tls_hostname_ok(host: str, timeout_s: float = 6.0) -> Tuple[bool, str]:
    ctx = ssl.create_default_context()
    with socket.create_connection((host, 443), timeout=timeout_s) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as ssock:
            cert = ssock.getpeercert()
            san = [v for (k, v) in cert.get("subjectAltName", ()) if k == "DNS"]
            if host in san:
                return True, "hostname TLS valide"
            return False, f"certificat non valide pour {host} (SAN: {san[:3]})"


def check_openai_network() -> CheckResult:
    ok_dns, dns_info = _dns_lookup("api.openai.com")
    if not ok_dns:
        return CheckResult("Réseau OpenAI", "FAIL", f"DNS KO: {dns_info}")
    try:
        ok_tls, tls_info = _tls_hostname_ok("api.openai.com")
    except Exception as e:
        return CheckResult("Réseau OpenAI", "FAIL", f"TLS KO: {e}")
    if not ok_tls:
        return CheckResult("Réseau OpenAI", "FAIL", tls_info)
    return CheckResult("Réseau OpenAI", "PASS", f"DNS/TLS OK ({dns_info})")


def check_hf_network() -> CheckResult:
    ok_dns, dns_info = _dns_lookup("huggingface.co")
    if not ok_dns:
        return CheckResult("Réseau HuggingFace", "WARN", f"DNS KO: {dns_info}")
    try:
        ok_tls, tls_info = _tls_hostname_ok("huggingface.co")
    except Exception as e:
        return CheckResult("Réseau HuggingFace", "WARN", f"TLS KO: {e}")
    if not ok_tls:
        return CheckResult("Réseau HuggingFace", "WARN", tls_info)
    return CheckResult("Réseau HuggingFace", "PASS", f"DNS/TLS OK ({dns_info})")


def check_python_deps() -> CheckResult:
    mods = {
        "openai": _has_module("openai"),
        "pyzbar": _has_module("pyzbar"),
        "mlx_vlm": _has_module("mlx_vlm"),
        "mlx_whisper": _has_module("mlx_whisper"),
    }
    missing = [k for k, v in mods.items() if not v]
    if not missing:
        return CheckResult("Dépendances Python", "PASS", "openai/pyzbar/mlx_vlm/mlx_whisper installés")
    return CheckResult("Dépendances Python", "WARN", f"manquants: {', '.join(missing)}")


def _hf_snapshots_present(model_repo: str) -> bool:
    model_dir_name = f"models--{model_repo.replace('/', '--')}"
    hf_home = (os.getenv("HF_HOME") or "").strip()
    cache_root = Path(hf_home).expanduser() / "hub" if hf_home else Path.home() / ".cache" / "huggingface" / "hub"
    snapshots = cache_root / model_dir_name / "snapshots"
    return snapshots.exists() and any(p.is_dir() for p in snapshots.iterdir())


def check_local_models() -> CheckResult:
    vlm_ok = _hf_snapshots_present("mlx-community/Qwen2-VL-2B-Instruct-4bit")
    stt_ok = _hf_snapshots_present("mlx-community/distil-whisper-large-v3")
    if vlm_ok and stt_ok:
        return CheckResult("Modèles locaux", "PASS", "VLM + STT local en cache")
    details = []
    details.append("VLM local OK" if vlm_ok else "VLM local absent")
    details.append("STT local OK" if stt_ok else "STT local absent")
    return CheckResult("Modèles locaux", "WARN", " / ".join(details))


def _find_barcode_test_image() -> Optional[Path]:
    candidates = [
        ROOT / "test_code barre shampoing.jpg",
        ROOT / "test_code_barre_shampoing.jpg",
    ]
    for p in candidates:
        if p.exists():
            return p
    jpgs = sorted(ROOT.glob("*code*barre*.jpg"))
    return jpgs[0] if jpgs else None


def check_barcode_decode_and_db() -> CheckResult:
    try:
        from PIL import Image
        from assistant.vision.vision_module import BarcodeDetector
        from assistant.database.database_module import ProductDatabase
    except Exception as e:
        return CheckResult("Barcode + DB", "FAIL", f"imports impossibles: {e}")

    image_path = _find_barcode_test_image()
    if not image_path:
        return CheckResult("Barcode + DB", "WARN", "image de test barcode non trouvée")

    detector = BarcodeDetector()
    if not getattr(detector, "_pyzbar_available", False):
        return CheckResult("Barcode + DB", "FAIL", "pyzbar/libzbar indisponible")

    image = Image.open(image_path).convert("RGB")
    values = detector.detect_single(image)
    if not values:
        return CheckResult("Barcode + DB", "FAIL", f"aucun code lu sur {image_path.name}")

    ean = values[0]
    db = ProductDatabase(str(ROOT / "data" / "products.db"))
    product = db.get_by_ean(ean)
    if not product:
        return CheckResult("Barcode + DB", "WARN", f"EAN lu {ean} absent de la base")

    name = getattr(product, "name", "") or ""
    brand = getattr(product, "brand", "") or ""
    return CheckResult("Barcode + DB", "PASS", f"EAN {ean} reconnu ({brand} {name})")


def check_required_eans() -> CheckResult:
    try:
        from assistant.database.database_module import ProductDatabase
    except Exception as e:
        return CheckResult("EAN de test", "FAIL", f"import DB impossible: {e}")

    required = {
        "8700216156950": "Head & Shoulders Classic",
        "3282770145373": "Klorane Extra Doux 400ml",
    }
    db = ProductDatabase(str(ROOT / "data" / "products.db"))
    missing = []
    for ean, label in required.items():
        if not db.get_by_ean(ean):
            missing.append(f"{ean} ({label})")
    if not missing:
        return CheckResult("EAN de test", "PASS", "les 2 EAN de test sont présents en base")
    return CheckResult("EAN de test", "WARN", f"EAN manquants: {', '.join(missing)}")


def main() -> int:
    _load_env()
    ca_path = _configure_tls_ca_bundle()
    checks: List[CheckResult] = [
        CheckResult("CA certifi", "PASS", ca_path) if ca_path else CheckResult("CA certifi", "WARN", "certifi non appliqué"),
        _safe("CA bundle Python", check_ca_bundle),
        _safe("OPENAI key", check_openai_key),
        _safe("Réseau OpenAI", check_openai_network),
        _safe("Réseau HuggingFace", check_hf_network),
        _safe("Dépendances Python", check_python_deps),
        _safe("Modèles locaux", check_local_models),
        _safe("Barcode + DB", check_barcode_decode_and_db),
        _safe("EAN de test", check_required_eans),
    ]

    print("\n=== Preflight Sans Robot ===")
    for c in checks:
        print(f"[{c.status}] {c.name}: {c.detail}")

    has_fail = any(c.status == "FAIL" for c in checks)
    has_warn = any(c.status == "WARN" for c in checks)
    print("\nRésumé:", "FAIL" if has_fail else ("WARN" if has_warn else "PASS"))
    return 2 if has_fail else (1 if has_warn else 0)


if __name__ == "__main__":
    raise SystemExit(main())
