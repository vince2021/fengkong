from __future__ import annotations

import json
import os
import platform
import subprocess
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4


SUPPORTED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg"}
MAX_OCR_PAGES = 5
_CACHE: dict[str, dict] = {}
_CACHE_LOCK = threading.Lock()


def run_document_ocr(content: bytes, filename: str, cache_key: str) -> dict:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        return _unavailable("当前格式不需要或不支持 OCR")
    if os.getenv("OCR_ENABLED", "auto").lower() in {"0", "false", "off"}:
        return _unavailable("OCR 已通过环境配置关闭")
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
    if cached is not None:
        return dict(cached)
    if platform.system() != "Darwin" or not Path("/usr/bin/clang").exists():
        return _unavailable("当前部署环境未配置 OCR 提供程序")
    source_path = Path(__file__).with_name("vision_ocr.m")
    if not source_path.exists():
        return _unavailable("OCR 适配器文件不存在")
    project_root = Path(__file__).resolve().parents[1]
    temp_root = project_root / "tmp" / "ocr"
    temp_root.mkdir(parents=True, exist_ok=True)
    binary_path = temp_root / "vision_ocr"
    compile_error = _ensure_binary(source_path, binary_path, temp_root)
    if compile_error:
        return _unavailable(compile_error)
    with TemporaryDirectory(dir=temp_root) as directory:
        input_path = Path(directory) / f"input{suffix}"
        input_path.write_bytes(content)
        try:
            completed = subprocess.run(
                [str(binary_path), str(input_path), str(MAX_OCR_PAGES)],
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=45,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return _error(f"OCR 执行失败：{type(exc).__name__}")
    try:
        payload = json.loads(completed.stdout.strip())
    except json.JSONDecodeError:
        payload = _error("OCR 返回结果无法解析")
    if completed.returncode != 0 and payload.get("status") != "error":
        payload = _error((completed.stderr or "OCR 进程异常退出")[:300])
    result = _normalize_result(payload)
    with _CACHE_LOCK:
        if len(_CACHE) >= 256:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[cache_key] = result
    return dict(result)


def _ensure_binary(source_path: Path, binary_path: Path, temp_root: Path) -> str | None:
    if binary_path.exists() and binary_path.stat().st_mtime >= source_path.stat().st_mtime:
        return None
    module_cache = temp_root / "module-cache"
    module_cache.mkdir(parents=True, exist_ok=True)
    temporary_binary = temp_root / f"vision_ocr.{os.getpid()}.{uuid4().hex}.tmp"
    environment = {**os.environ, "CLANG_MODULE_CACHE_PATH": str(module_cache)}
    try:
        completed = subprocess.run(
            [
                "/usr/bin/clang", "-fobjc-arc", "-fmodules",
                "-framework", "Foundation", "-framework", "Vision",
                "-framework", "AppKit", "-framework", "PDFKit",
                str(source_path), "-o", str(temporary_binary),
            ],
            cwd=source_path.parents[1],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired):
        temporary_binary.unlink(missing_ok=True)
        return "OCR 本地适配器编译超时或不可用，已降级为人工核验"
    if completed.returncode != 0:
        temporary_binary.unlink(missing_ok=True)
        return "OCR 本地适配器编译失败，已降级为人工核验"
    os.replace(temporary_binary, binary_path)
    return None


def _normalize_result(payload: dict) -> dict:
    lines = [
        {
            "text": str(item.get("text", ""))[:500],
            "confidence": round(float(item.get("confidence", 0)), 4),
            "page": int(item.get("page", 1)),
        }
        for item in payload.get("lines", [])[:500]
        if str(item.get("text", "")).strip()
    ]
    average_confidence = round(sum(item["confidence"] for item in lines) / len(lines), 4) if lines else 0.0
    return {
        "status": payload.get("status", "error"),
        "provider": payload.get("provider", "macos_vision"),
        "pages_processed": min(max(int(payload.get("pagesProcessed", 0)), 0), MAX_OCR_PAGES),
        "average_confidence": average_confidence,
        "lines": lines,
        "warning": payload.get("warning"),
    }


def _unavailable(reason: str) -> dict:
    return {"status": "unavailable", "provider": None, "pages_processed": 0, "average_confidence": 0.0, "lines": [], "warning": reason}


def _error(reason: str) -> dict:
    return {"status": "error", "provider": "macos_vision", "pages_processed": 0, "average_confidence": 0.0, "lines": [], "warning": reason}
