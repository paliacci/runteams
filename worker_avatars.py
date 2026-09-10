"""Managed worker avatar presets and local uploads."""

import base64
import binascii
import copy
import io
import os
import re
import secrets

from PIL import Image, ImageOps, UnidentifiedImageError


PRESET_IDS = (
    "ada",
    "alan",
    "aso-specialist",
    "atlas",
    "commercial-manager",
    "cora",
    "echo",
    "grace",
    "juno",
    "localization-specialist",
    "market-analyst",
    "nova",
    "product-manager",
    "qa-engineer",
    "software-architect",
    "user-operations",
)
LEGACY_RE = re.compile(r"^a[1-6]$")
UPLOAD_RE = re.compile(r"^upload:([a-f0-9]{24}\.webp)$")
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


def preset_reference(preset_id):
    return "preset:bottts:{}".format(preset_id)


def preset_items():
    return [
        {
            "id": preset_id,
            "avatar": preset_reference(preset_id),
            "src": "/worker-avatars/bottts/{}.svg".format(preset_id),
        }
        for preset_id in PRESET_IDS
    ]


def _upload_root(data_dir):
    root = os.path.join(data_dir, "worker-avatars")
    os.makedirs(root, exist_ok=True)
    return root


def upload_path(reference, data_dir):
    match = UPLOAD_RE.fullmatch(str(reference or ""))
    if not match:
        return None
    return os.path.join(_upload_root(data_dir), match.group(1))


def normalize_reference(reference, data_dir, allow_missing_upload=False):
    value = str(reference or "").strip()
    if not value:
        return "a1"
    if LEGACY_RE.fullmatch(value):
        return value
    if value.startswith("preset:bottts:") and value.split(":", 2)[2] in PRESET_IDS:
        return value
    path = upload_path(value, data_dir)
    if path and (allow_missing_upload or os.path.isfile(path)):
        return value
    raise ValueError("头像无效")


def public_src(reference):
    value = str(reference or "")
    if value.startswith("preset:bottts:"):
        preset_id = value.split(":", 2)[2]
        if preset_id in PRESET_IDS:
            return "/worker-avatars/bottts/{}.svg".format(preset_id)
    match = UPLOAD_RE.fullmatch(value)
    if match:
        return "/api/worker-avatar/upload/{}".format(match.group(1))
    return ""


def save_upload(payload, data_dir):
    encoded = str((payload or {}).get("data") or "")
    if "," in encoded and encoded.lstrip().startswith("data:"):
        encoded = encoded.split(",", 1)[1]
    if not encoded or len(encoded) > (MAX_UPLOAD_BYTES * 4 // 3) + 4096:
        raise ValueError("请选择不超过 5 MB 的图片")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("图片数据无效")
    if not raw or len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError("请选择不超过 5 MB 的图片")
    try:
        with Image.open(io.BytesIO(raw)) as source:
            image = ImageOps.exif_transpose(source)
            if image.width < 32 or image.height < 32:
                raise ValueError("图片尺寸太小")
            if max(image.width, image.height) > 12000:
                raise ValueError("图片尺寸过大")
            image = image.convert("RGBA") if "A" in image.getbands() else image.convert("RGB")
            image = ImageOps.fit(image, (512, 512), method=Image.Resampling.LANCZOS)
            filename = "{}.webp".format(secrets.token_hex(12))
            path = os.path.join(_upload_root(data_dir), filename)
            image.save(path, "WEBP", quality=88, method=6)
    except UnidentifiedImageError:
        raise ValueError("不支持这种图片格式")
    reference = "upload:{}".format(filename)
    return {"avatar": reference, "src": public_src(reference)}


def remove_upload(reference, data_dir):
    path = upload_path(reference, data_dir)
    if not path:
        return False
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def include_export_assets(bundle, data_dir):
    """Embed uploaded avatars so exported pipelines remain portable."""
    result = copy.deepcopy(bundle)
    assets = {}
    for worker in result.get("workers") or []:
        reference = str(worker.get("avatar") or "")
        path = upload_path(reference, data_dir)
        if not path or not os.path.isfile(path):
            continue
        with open(path, "rb") as handle:
            assets[reference] = base64.b64encode(handle.read()).decode("ascii")
    if assets:
        result["worker_avatar_assets"] = assets
    return result


def materialize_import_assets(bundle, data_dir):
    """Restore embedded uploaded avatars before importing worker records."""
    result = copy.deepcopy(bundle)
    assets = result.pop("worker_avatar_assets", {})
    if not isinstance(assets, dict):
        assets = {}
    replacements = {}
    for old_reference, encoded in assets.items():
        if not UPLOAD_RE.fullmatch(str(old_reference or "")):
            continue
        try:
            saved = save_upload({"data": encoded}, data_dir)
        except ValueError:
            continue
        replacements[str(old_reference)] = saved["avatar"]
    for worker in result.get("workers") or []:
        reference = str(worker.get("avatar") or "")
        if reference in replacements:
            worker["avatar"] = replacements[reference]
        else:
            try:
                worker["avatar"] = normalize_reference(reference, data_dir)
            except ValueError:
                worker["avatar"] = "a1"
    return result
