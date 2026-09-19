from __future__ import annotations
import base64, hashlib, json, os, re, secrets, shutil, time, urllib.parse
from pathlib import Path
from typing import Any
from .config import CACHE_DIR, CATALOG_TTL, DETAIL_TTL, FONTSOURCE_API, LOCAL_DIR, MAX_UPLOAD, NOTO_COLOR_EMOJI, STATE_DIR, atomic_write, fetch_bytes, sh

def fetch_json(url: str, timeout: int = 45) -> Any:
    return json.loads(fetch_bytes(url, timeout).decode("utf-8"))

def cached_json(name: str, url: str, ttl: int) -> Any:
    path = CACHE_DIR / name
    if path.exists() and time.time() - path.stat().st_mtime < ttl:
        return json.loads(path.read_text())
    data = fetch_json(url)
    atomic_write(path, json.dumps(data, ensure_ascii=False).encode("utf-8"))
    return data

def catalog() -> list[dict[str, Any]]:
    return cached_json("fontsource-catalog.json", f"{FONTSOURCE_API}/fonts", CATALOG_TTL)

def font_detail(font_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"[a-z0-9-]+", font_id):
        raise ValueError("Invalid font id")
    return cached_json(f"font-{font_id}.json", f"{FONTSOURCE_API}/fonts/{font_id}", DETAIL_TTL)

def load_state() -> dict[str, Any]:
    p = STATE_DIR / "selection.json"
    if not p.exists():
        return {"fonts": [], "emoji": True, "fullPacks": True, "appliedAt": None}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {"fonts": [], "emoji": True, "fullPacks": True, "appliedAt": None}

def save_state(state: dict[str, Any]) -> None:
    atomic_write(STATE_DIR / "selection.json", json.dumps(state, indent=2).encode("utf-8"))

def iter_variant_files(detail: dict[str, Any], full_packs: bool) -> list[dict[str, str]]:
    variants = detail.get("variants") or {}
    preferred_subset = detail.get("defSubset") or "latin"
    found, seen = [], set()
    for weight, styles in variants.items():
        if not isinstance(styles, dict): continue
        for style, subsets in styles.items():
            if not isinstance(subsets, dict): continue
            for subset, info in subsets.items():
                if not full_packs and subset != preferred_subset: continue
                if not isinstance(info, dict): continue
                urls = info.get("url") or {}
                url = urls.get("ttf") or urls.get("woff2") or urls.get("woff")
                if not url or url in seen: continue
                seen.add(url)
                found.append({"url": url, "weight": str(weight), "style": str(style), "subset": str(subset)})
    return found

def clean_filename(url: str) -> str:
    name = Path(urllib.parse.urlparse(url).path).name
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return name or f"font-{secrets.token_hex(4)}.woff2"

def download_family(font_id: str, target_root: Path, full_packs: bool) -> dict[str, Any]:
    detail = font_detail(font_id)
    family = detail.get("family") or font_id
    files = iter_variant_files(detail, full_packs)
    if not files: raise RuntimeError(f"No installable variants found for {family}")
    fam_dir = target_root / font_id; fam_dir.mkdir(parents=True, exist_ok=True)
    manifest_files = []
    for item in files:
        name = clean_filename(item["url"]); dest = fam_dir / name
        if not dest.exists(): atomic_write(dest, fetch_bytes(item["url"], timeout=90))
        manifest_files.append({**item, "file": f"{font_id}/{name}"})
    return {"id": font_id, "family": family, "category": detail.get("category", "other"), "type": detail.get("type", "unknown"), "license": "Open-source via Fontsource", "files": manifest_files}

def download_emoji(target_root: Path) -> dict[str, Any]:
    eid = "noto-color-emoji"; d = target_root / eid; d.mkdir(parents=True, exist_ok=True)
    dest = d / "NotoColorEmoji.ttf"
    if not dest.exists(): atomic_write(dest, fetch_bytes(NOTO_COLOR_EMOJI, timeout=120))
    return {"id": eid, "family": "Noto Color Emoji", "category": "emoji", "type": "emoji", "license": "SIL Open Font License 1.1", "files": [{"file": f"{eid}/{dest.name}", "weight": "400", "style": "normal", "subset": "emoji", "url": NOTO_COLOR_EMOJI}]}

def local_manifests() -> list[dict[str, Any]]:
    out = []
    for meta in sorted(LOCAL_DIR.glob("*/manifest.json")):
        try: out.append(json.loads(meta.read_text()))
        except Exception: pass
    return out

def local_family_name(path: Path) -> str:
    try:
        cp = sh(["fc-scan", "--format", "%{family[0]}", str(path)], check=False)
        if cp.returncode == 0 and cp.stdout.strip(): return cp.stdout.strip()
    except Exception: pass
    return path.stem

def install_local_upload(name: str, data: bytes, license_note: str) -> dict[str, Any]:
    if len(data) > MAX_UPLOAD: raise ValueError("File is larger than 40 MiB")
    ext = Path(name).suffix.lower()
    if ext not in {".ttf", ".otf", ".woff", ".woff2"}: raise ValueError("Supported uploads: TTF, OTF, WOFF and WOFF2")
    digest = hashlib.sha256(data).hexdigest()[:12]
    lid = "local-" + re.sub(r"[^a-z0-9]+", "-", Path(name).stem.lower()).strip("-")[:50] + "-" + digest
    d = LOCAL_DIR / lid; d.mkdir(parents=True, exist_ok=True)
    dest = d / re.sub(r"[^A-Za-z0-9._-]", "_", Path(name).name); atomic_write(dest, data)
    family = local_family_name(dest)
    manifest = {"id": lid, "family": family, "category": "local", "type": "local", "license": license_note or "Administrator supplied", "files": [{"file": f"{lid}/{dest.name}", "weight": "400", "style": "normal", "subset": "all", "source": str(dest)}]}
    atomic_write(d / "manifest.json", json.dumps(manifest, indent=2).encode("utf-8"))
    return manifest

def preview_url(font_id: str) -> str:
    detail = font_detail(font_id); files = iter_variant_files(detail, False)
    if not files: raise RuntimeError("No preview variant")
    choice = next((f for f in files if f["weight"] == "400" and f["style"] == "normal"), files[0])
    variants = detail.get("variants") or {}; urls = []
    for weight, styles in variants.items():
        for style, subsets in (styles or {}).items():
            for subset, info in (subsets or {}).items():
                if subset == (detail.get("defSubset") or "latin") and str(weight) == choice["weight"] and str(style) == choice["style"]:
                    u = (info.get("url") or {}).get("woff2")
                    if u: urls.append(u)
    return urls[0] if urls else choice["url"]
