# -*- coding: utf-8 -*-
"""对话附件：保存原件，并生成 Claude Code / Codex 都能消费的标准输入。"""
import base64
import binascii
import io
import json
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import warnings

import pymupdf
from PIL import Image, ImageOps

import product_store


MAX_FILES = 10
MAX_NATIVE_FILES = 100
MAX_NATIVE_SELECTIONS = 10
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 25 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
MAX_IMAGE_EDGE = 12_000
MAX_PDF_PAGES = 20
MAX_RENDERED_IMAGES = 24
MAX_EXTRACTED_TEXT_CHARS = 2_000_000
PDF_RENDER_DPI = 144

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl",
    ".yaml", ".yml", ".xml", ".html", ".htm", ".css", ".scss", ".less",
    ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".py", ".rb", ".php",
    ".java", ".kt", ".kts", ".swift", ".go", ".rs", ".c", ".h", ".cc",
    ".cpp", ".hpp", ".cs", ".sh", ".zsh", ".fish", ".sql", ".toml", ".ini",
    ".cfg", ".conf", ".log", ".ipynb",
    # Apple project metadata and resources are UTF-8 text too. Omitting these
    # silently turns a selected Xcode project into an incomplete snapshot.
    ".plist", ".strings", ".stringsdict", ".xcstrings", ".xcprivacy",
    ".entitlements", ".storekit", ".pbxproj", ".xcscheme",
    ".xcworkspacedata", ".modulemap", ".metal",
}
ALLOWED_EXTENSIONS = IMAGE_EXTENSIONS | TEXT_EXTENSIONS | {".pdf"}
_IMAGE_FORMATS = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}
_IGNORED_DIRECTORIES = {".git", ".svn", ".hg", "node_modules", "__pycache__"}
_SELECTION_TTL = 30 * 60
_SELECTIONS = {}
_SELECTIONS_LOCK = threading.Lock()


def _selection_root():
    path = os.path.join(product_store.assistant_workspace(), ".attachment-staging")
    os.makedirs(path, exist_ok=True)
    return path


def _picker_candidates():
    configured = os.environ.get("RUNTEAMS_ATTACHMENT_PICKER")
    if configured:
        yield os.path.abspath(os.path.expanduser(configured))
    if getattr(sys, "frozen", False):
        resources = os.path.dirname(os.path.dirname(sys.executable))
        yield os.path.join(resources, "RunTeamsPicker.app", "Contents", "MacOS", "RunTeamsPicker")
        yield os.path.join(resources, "RunTeamsPicker")
    root = os.path.dirname(os.path.abspath(__file__))
    yield os.path.join(root, "desktop", "RunTeams.app", "Contents", "Resources",
                       "RunTeamsPicker.app", "Contents", "MacOS", "RunTeamsPicker")
    yield os.path.join(root, "desktop", "RunTeams.app", "Contents", "Resources", "RunTeamsPicker")


def native_picker_path():
    if sys.platform != "darwin":
        return ""
    for path in _picker_candidates():
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return ""


def native_picker_available():
    return bool(native_picker_path())


def _cleanup_selections():
    cutoff = time.time() - _SELECTION_TTL
    stale = []
    with _SELECTIONS_LOCK:
        for token, item in list(_SELECTIONS.items()):
            if item.get("created_at", 0) < cutoff:
                stale.append(_SELECTIONS.pop(token))
    for item in stale:
        shutil.rmtree(item.get("stage_dir") or "", ignore_errors=True)


def _allowed_file(path):
    return os.path.splitext(path)[1].lower() in ALLOWED_EXTENSIONS


def _folder_files(root):
    result = []
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs
                         if not d.startswith(".") and d not in _IGNORED_DIRECTORIES
                         and not os.path.islink(os.path.join(current, d)))
        for name in sorted(files):
            path = os.path.join(current, name)
            if name.startswith(".") or os.path.islink(path) or not _allowed_file(path):
                continue
            result.append((path, os.path.relpath(path, root)))
    return result


def _stage_native_paths(paths):
    """把原生面板返回的路径复制成一次性快照；绝不把绝对路径返回给前端。"""
    _cleanup_selections()
    unique = []
    for raw in paths or []:
        path = os.path.realpath(os.path.abspath(os.path.expanduser(str(raw or ""))))
        if path and path not in unique:
            unique.append(path)
    if len(unique) > MAX_NATIVE_SELECTIONS:
        raise ValueError("一次最多选择 {} 个文件或文件夹".format(MAX_NATIVE_SELECTIONS))
    if not unique:
        return []

    staged, created_dirs, total_bytes, total_files = [], [], 0, 0

    def account(path):
        nonlocal total_bytes, total_files
        try:
            size = os.path.getsize(path)
        except OSError:
            raise ValueError("所选内容已不存在或无法读取")
        if size <= 0:
            raise ValueError("不能添加空文件「{}」".format(os.path.basename(path)))
        if size > MAX_FILE_BYTES:
            raise ValueError("「{}」超过 10 MB".format(os.path.basename(path)))
        total_files += 1
        total_bytes += size
        if total_files > MAX_NATIVE_FILES:
            raise ValueError("文件夹内最多处理 {} 个支持的文件".format(MAX_NATIVE_FILES))
        if total_bytes > MAX_TOTAL_BYTES:
            raise ValueError("所选内容总大小不能超过 25 MB")
        return size

    try:
        for source in unique:
            if os.path.islink(source) or not os.path.exists(source):
                raise ValueError("暂不支持符号链接或不存在的路径")
            token = secrets.token_hex(16)
            stage_dir = os.path.join(_selection_root(), token)
            os.makedirs(stage_dir, exist_ok=False)
            created_dirs.append(stage_dir)
            if os.path.isfile(source):
                if not _allowed_file(source):
                    raise ValueError("暂不支持 {} 格式".format(os.path.splitext(source)[1] or "无扩展名"))
                size = account(source)
                name = _safe_name(os.path.basename(source))
                target = os.path.join(stage_dir, name)
                shutil.copyfile(source, target)
                record = {"token": token, "kind": "image" if os.path.splitext(name)[1] in IMAGE_EXTENSIONS else "file",
                          "name": name, "size": size, "file_count": 1, "path": target,
                          "stage_dir": stage_dir, "created_at": time.time()}
            elif os.path.isdir(source):
                name = os.path.basename(source.rstrip(os.sep)) or "文件夹"
                if name.startswith(".") or name in _IGNORED_DIRECTORIES:
                    raise ValueError("不能添加隐藏目录或依赖目录「{}」".format(name))
                files = _folder_files(source)
                if not files:
                    raise ValueError("文件夹「{}」中没有支持的文件".format(name))
                folder_target = os.path.join(stage_dir, "folder")
                os.makedirs(folder_target)
                folder_size = 0
                for path, relative in files:
                    folder_size += account(path)
                    destination = os.path.join(folder_target, relative)
                    os.makedirs(os.path.dirname(destination), exist_ok=True)
                    shutil.copyfile(path, destination)
                record = {"token": token, "kind": "folder", "name": name[:120],
                          "size": folder_size, "file_count": len(files), "path": folder_target,
                          "stage_dir": stage_dir, "created_at": time.time()}
            else:
                raise ValueError("所选内容不是文件或文件夹")
            staged.append(record)
        with _SELECTIONS_LOCK:
            for record in staged:
                _SELECTIONS[record["token"]] = record
        return [{k: record.get(k) for k in ("token", "kind", "name", "size", "file_count")}
                for record in staged]
    except Exception:
        for path in created_dirs:
            shutil.rmtree(path, ignore_errors=True)
        raise


def pick_native():
    picker = native_picker_path()
    if not picker:
        raise ValueError("当前环境不支持系统文件夹选择器")
    try:
        result = subprocess.run([picker], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, timeout=600)
    except subprocess.TimeoutExpired:
        raise ValueError("文件选择已超时，请重试")
    except OSError:
        raise ValueError("无法打开系统文件选择器")
    if result.returncode:
        raise ValueError((result.stderr or "系统文件选择器运行失败").strip()[:300])
    try:
        payload = json.loads(result.stdout or "{}")
    except ValueError:
        raise ValueError("系统文件选择器返回了无效结果")
    if payload.get("cancelled"):
        return []
    return _stage_native_paths(payload.get("paths") or [])


def _chat_dir(chat_id):
    return os.path.join(product_store.assistant_workspace(), "chat-{}".format(int(chat_id)), "attachments")


def _safe_name(name):
    name = os.path.basename((name or "attachment").replace("\x00", "")).strip()
    stem, ext = os.path.splitext(name)
    stem = re.sub(r"[^\w.()\- ]+", "_", stem, flags=re.UNICODE).strip(" .")[:80] or "attachment"
    return stem + ext.lower()


def _decode(payload):
    encoded = payload.get("data") or ""
    if "," in encoded and encoded.lstrip().startswith("data:"):
        encoded = encoded.split(",", 1)[1]
    try:
        return base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("附件内容无效")


def _contained_path(chat_id, stored_name, require_file=True):
    root = os.path.realpath(_chat_dir(chat_id))
    path = os.path.realpath(os.path.join(root, stored_name or ""))
    try:
        contained = os.path.commonpath((root, path)) == root
    except ValueError:
        contained = False
    if not contained or (require_file and not os.path.isfile(path)):
        raise ValueError("附件不存在")
    return path


def _write_bytes(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "xb") as handle:
        handle.write(data)


def _normalize_text(data, name, item_dir, item_rel):
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("附件「{}」不是 UTF-8 文本".format(name))
    if "\x00" in text:
        raise ValueError("附件「{}」包含二进制内容".format(name))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized_name = "content.txt"
    _write_bytes(os.path.join(item_dir, normalized_name), text.encode("utf-8"))
    return [{"kind": "text", "stored_name": item_rel + "/" + normalized_name,
             "label": "UTF-8 文本"}]


def _check_image_size(image, name):
    width, height = image.size
    if width <= 0 or height <= 0 or width > MAX_IMAGE_EDGE or height > MAX_IMAGE_EDGE:
        raise ValueError("图片「{}」尺寸超出限制".format(name))
    if width * height > MAX_IMAGE_PIXELS:
        raise ValueError("图片「{}」像素过大".format(name))
    if getattr(image, "n_frames", 1) != 1:
        raise ValueError("暂不支持动态图「{}」".format(name))


def _save_canonical_image(image, name, item_dir, item_rel):
    image = ImageOps.exif_transpose(image)
    has_alpha = image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info)
    if has_alpha:
        normalized_name = "image.png"
        image.convert("RGBA").save(os.path.join(item_dir, normalized_name), "PNG", optimize=True)
    else:
        normalized_name = "image.jpg"
        image.convert("RGB").save(os.path.join(item_dir, normalized_name), "JPEG",
                                  quality=92, optimize=True, progressive=True)
    return [{"kind": "image", "stored_name": item_rel + "/" + normalized_name,
             "label": "标准图片"}]


def _normalize_image(data, name, ext, item_dir, item_rel):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as probe:
                if probe.format != _IMAGE_FORMATS[ext]:
                    raise ValueError("图片格式与扩展名不一致")
                _check_image_size(probe, name)
                probe.verify()
            with Image.open(io.BytesIO(data)) as image:
                _check_image_size(image, name)
                image.load()
                return _save_canonical_image(image, name, item_dir, item_rel)
    except ValueError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError("图片「{}」像素过大".format(name))
    except Exception:
        raise ValueError("图片「{}」已损坏或格式无效".format(name))


def _normalize_pdf(data, name, item_dir, item_rel):
    if not data.lstrip().startswith(b"%PDF-"):
        raise ValueError("PDF「{}」格式无效".format(name))
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        raise ValueError("PDF「{}」已损坏或格式无效".format(name))
    normalized = []
    try:
        if document.needs_pass:
            raise ValueError("PDF「{}」受密码保护，无法读取".format(name))
        if document.page_count < 1:
            raise ValueError("PDF「{}」没有可读取的页面".format(name))
        if document.page_count > MAX_PDF_PAGES:
            raise ValueError("PDF「{}」超过 {} 页，请拆分后上传".format(name, MAX_PDF_PAGES))
        texts = []
        scale = PDF_RENDER_DPI / 72.0
        matrix = pymupdf.Matrix(scale, scale)
        for index, page in enumerate(document):
            texts.append("\n\n===== 第 {} 页 =====\n{}".format(index + 1, page.get_text("text")))
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            if pixmap.width * pixmap.height > MAX_IMAGE_PIXELS:
                raise ValueError("PDF「{}」第 {} 页尺寸过大".format(name, index + 1))
            page_name = "page-{:03d}.png".format(index + 1)
            pixmap.save(os.path.join(item_dir, page_name))
            normalized.append({"kind": "image", "stored_name": item_rel + "/" + page_name,
                               "label": "第 {} 页图像".format(index + 1), "page": index + 1})
        text = "".join(texts).strip()
        if len(text) > MAX_EXTRACTED_TEXT_CHARS:
            raise ValueError("PDF「{}」提取出的文本过长，请拆分后上传".format(name))
        text_name = "content.txt"
        _write_bytes(os.path.join(item_dir, text_name), text.encode("utf-8"))
        normalized.insert(0, {"kind": "text", "stored_name": item_rel + "/" + text_name,
                              "label": "PDF 提取文本"})
        return normalized
    except ValueError:
        raise
    except Exception:
        raise ValueError("PDF「{}」解析失败".format(name))
    finally:
        document.close()


def _normalize(data, name, ext, item_dir, item_rel):
    if ext in IMAGE_EXTENSIONS:
        return _normalize_image(data, name, ext, item_dir, item_rel)
    if ext == ".pdf":
        return _normalize_pdf(data, name, item_dir, item_rel)
    return _normalize_text(data, name, item_dir, item_rel)


def save(chat_id, uploads):
    uploads = uploads or []
    if len(uploads) > MAX_FILES:
        raise ValueError("每次最多添加 {} 个附件".format(MAX_FILES))
    prepared, total = [], 0
    for upload in uploads:
        name = _safe_name(upload.get("name"))
        ext = os.path.splitext(name)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError("暂不支持 {} 格式".format(ext or "无扩展名"))
        data = _decode(upload)
        if not data:
            raise ValueError("附件「{}」是空文件".format(name))
        if len(data) > MAX_FILE_BYTES:
            raise ValueError("附件「{}」超过 10 MB".format(name))
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise ValueError("附件总大小不能超过 25 MB")
        prepared.append((upload, name, ext, data))

    saved, created_dirs, rendered_images = [], [], 0
    target = _chat_dir(chat_id)
    try:
        for upload, name, ext, data in prepared:
            os.makedirs(target, exist_ok=True)
            attachment_id = secrets.token_hex(12)
            item_rel = attachment_id
            item_dir = _contained_path(chat_id, item_rel, require_file=False)
            os.makedirs(item_dir, exist_ok=False)
            created_dirs.append(item_dir)
            original_name = "original" + ext
            _write_bytes(os.path.join(item_dir, original_name), data)
            normalized = _normalize(data, name, ext, item_dir, item_rel)
            rendered_images += sum(x.get("kind") == "image" for x in normalized)
            if rendered_images > MAX_RENDERED_IMAGES:
                raise ValueError("本次附件转换后超过 {} 张图片，请分批发送".format(MAX_RENDERED_IMAGES))
            mime = (mimetypes.guess_type(name)[0] or upload.get("mime_type") or
                    "application/octet-stream")[:120]
            saved.append({
                "id": attachment_id,
                "name": name,
                "mime_type": mime,
                "size": len(data),
                "kind": "image" if ext in IMAGE_EXTENSIONS else "file",
                "stored_name": item_rel + "/" + original_name,
                "normalized": normalized,
            })
        return saved
    except Exception:
        for path in created_dirs:
            shutil.rmtree(path, ignore_errors=True)
        raise


def consume_native_to(target, tokens, max_total_bytes=MAX_TOTAL_BYTES):
    """消费一次性选择令牌并落到指定的受管目录；成功后令牌立即失效。"""
    _cleanup_selections()
    tokens = list(dict.fromkeys(str(token or "") for token in (tokens or []) if token))
    if not tokens:
        return []
    if len(tokens) > MAX_NATIVE_SELECTIONS:
        raise ValueError("一次最多选择 {} 个文件或文件夹".format(MAX_NATIVE_SELECTIONS))
    with _SELECTIONS_LOCK:
        records = [_SELECTIONS.get(token) for token in tokens]
    if any(not record for record in records):
        raise ValueError("附件选择已过期，请重新选择")
    total = sum(int(record.get("size") or 0) for record in records)
    if total > max(0, int(max_total_bytes or 0)):
        raise ValueError("附件总大小不能超过 25 MB")

    saved, created_dirs, rendered_images = [], [], 0
    target = os.path.realpath(target)
    os.makedirs(target, exist_ok=True)
    try:
        for record in records:
            os.makedirs(target, exist_ok=True)
            attachment_id = secrets.token_hex(12)
            item_rel = attachment_id
            item_dir = os.path.realpath(os.path.join(target, item_rel))
            try:
                if os.path.commonpath((target, item_dir)) != target:
                    raise ValueError("附件保存路径无效")
            except ValueError:
                raise ValueError("附件保存路径无效")
            os.makedirs(item_dir, exist_ok=False)
            created_dirs.append(item_dir)
            if record["kind"] == "folder":
                folder_name = "folder"
                shutil.copytree(record["path"], os.path.join(item_dir, folder_name))
                saved.append({
                    "id": attachment_id, "name": record["name"], "mime_type": "inode/directory",
                    "size": record["size"], "kind": "folder", "file_count": record["file_count"],
                    "stored_name": item_rel + "/" + folder_name,
                    "normalized": [{"kind": "folder", "stored_name": item_rel + "/" + folder_name,
                                    "label": "文件夹快照"}],
                })
                continue
            name = _safe_name(record["name"])
            ext = os.path.splitext(name)[1].lower()
            with open(record["path"], "rb") as handle:
                data = handle.read()
            original_name = "original" + ext
            _write_bytes(os.path.join(item_dir, original_name), data)
            normalized = _normalize(data, name, ext, item_dir, item_rel)
            rendered_images += sum(item.get("kind") == "image" for item in normalized)
            if rendered_images > MAX_RENDERED_IMAGES:
                raise ValueError("本次附件转换后超过 {} 张图片，请分批发送".format(MAX_RENDERED_IMAGES))
            saved.append({
                "id": attachment_id, "name": name,
                "mime_type": mimetypes.guess_type(name)[0] or "application/octet-stream",
                "size": len(data), "kind": "image" if ext in IMAGE_EXTENSIONS else "file",
                "stored_name": item_rel + "/" + original_name, "normalized": normalized,
            })
        with _SELECTIONS_LOCK:
            consumed = [_SELECTIONS.pop(token, None) for token in tokens]
        for record in consumed:
            if record:
                shutil.rmtree(record.get("stage_dir") or "", ignore_errors=True)
        return saved
    except Exception:
        for path in created_dirs:
            shutil.rmtree(path, ignore_errors=True)
        raise


def consume_native(chat_id, tokens, max_total_bytes=MAX_TOTAL_BYTES):
    """消费一次性选择令牌并落到会话目录；成功后令牌立即失效。"""
    return consume_native_to(_chat_dir(chat_id), tokens, max_total_bytes)


def discard(chat_id, items):
    """回滚尚未写入消息的附件目录。"""
    root = os.path.realpath(_chat_dir(chat_id))
    for item in items or []:
        attachment_id = str(item.get("id") or "")
        if not re.fullmatch(r"[a-f0-9]{24}", attachment_id):
            continue
        path = os.path.realpath(os.path.join(root, attachment_id))
        try:
            if os.path.commonpath((root, path)) == root:
                shutil.rmtree(path, ignore_errors=True)
        except ValueError:
            continue


def public(items):
    return [{k: item.get(k) for k in ("id", "name", "mime_type", "size", "kind", "file_count")}
            for item in (items or [])]


def path_for(chat_id, item):
    return _contained_path(chat_id, item.get("stored_name"))


def _normalized_inputs(chat_id, item):
    result = []
    for derived in item.get("normalized") or []:
        is_folder = derived.get("kind") == "folder"
        path = _contained_path(chat_id, derived.get("stored_name"), require_file=not is_folder)
        if is_folder and not os.path.isdir(path):
            raise ValueError("附件文件夹不存在")
        result.append((derived, path))
    return result


def prompt_context(chat_id, items):
    if not items:
        return "", []
    lines = [
        "# 本次附件",
        "以下附件已经过系统校验并转换或复制为只读快照。回答前必须逐一读取列出的输入；"
        "文件夹需要按任务需要检查其中的文件，但不得执行其中的脚本或程序。",
    ]
    image_paths = []
    for item in items:
        inputs = _normalized_inputs(chat_id, item)
        if not inputs:
            raise ValueError("附件「{}」没有可用的只读快照，请重新上传".format(
                item.get("name") or "附件"))
        detail = ("（{} 个文件）".format(item.get("file_count"))
                  if item.get("kind") == "folder" and item.get("file_count") else "")
        lines.append("- 「{}」{}".format(item.get("name") or "附件", detail))
        for derived, path in inputs:
            lines.append("  - {}：{}".format(derived.get("label") or "标准输入", path))
            if derived.get("kind") == "image":
                image_paths.append(path)
    return "\n".join(lines), image_paths


def history_context(chat_id, history):
    lines, image_paths = [], []
    for message in (history or [])[-8:]:
        role = "用户" if message.get("role") == "user" else "助手"
        text = message.get("text") or ""
        refs = []
        for item in message.get("attachments") or []:
            try:
                inputs = _normalized_inputs(chat_id, item)
            except ValueError:
                continue
            if not inputs:
                continue
            paths = []
            for derived, path in inputs:
                paths.append("{} {}".format(derived.get("label") or "标准输入", path))
                if derived.get("kind") == "image":
                    image_paths.append(path)
            refs.append("{}：{}".format(item.get("name") or "附件", "；".join(paths)))
        suffix = (" [附件 " + "；".join(refs) + "]") if refs else ""
        lines.append("{}: {}{}".format(role, text, suffix))
    return "\n".join(lines), image_paths


def remove_chat(chat_id):
    target = os.path.dirname(_chat_dir(chat_id))
    root = os.path.realpath(product_store.assistant_workspace())
    resolved = os.path.realpath(target)
    if os.path.dirname(resolved) == root and os.path.isdir(resolved):
        shutil.rmtree(resolved)
