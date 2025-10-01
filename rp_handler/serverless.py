#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import os
import pathlib
import tempfile
import urllib.request
from typing import Any, Dict, Optional

try:
    import runpod  # type: ignore
except Exception as exc:  # pragma: no cover
    raise RuntimeError("runpod package is required for serverless adapter. Install 'runpod'.") from exc

from .workflow import run_workflow
from .utils import log_info, log_warn, log_error


def _infer_mime_type(extension: str) -> str:
    """Определить MIME type по расширению файла."""
    extension = extension.lower().lstrip(".")
    
    mime_map = {
        # Изображения
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "webp": "image/webp",
        "bmp": "image/bmp",
        "tiff": "image/tiff",
        "tif": "image/tiff",
        # Видео
        "mp4": "video/mp4",
        "avi": "video/x-msvideo",
        "mov": "video/quicktime",
        "mkv": "video/x-matroska",
        "webm": "video/webm",
        "flv": "video/x-flv",
        # Аудио
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "ogg": "audio/ogg",
        "flac": "audio/flac",
        # Другое
        "json": "application/json",
        "zip": "application/zip",
        "tar": "application/x-tar",
        "gz": "application/gzip",
    }
    
    return mime_map.get(extension, "application/octet-stream")


def _download_to_temp(url: str) -> str:
    fd, tmp_path = tempfile.mkstemp(prefix="workflow_", suffix=".json")
    os.close(fd)
    with urllib.request.urlopen(url) as resp, open(tmp_path, "wb") as f:
        f.write(resp.read())
    return tmp_path


def _write_json_to_temp(data: Any) -> str:
    fd, tmp_path = tempfile.mkstemp(prefix="workflow_", suffix=".json")
    os.close(fd)
    # data может быть dict или строка JSON
    if isinstance(data, (dict, list)):
        payload = json.dumps(data, ensure_ascii=False)
    elif isinstance(data, str):
        payload = data
    else:
        raise ValueError("workflow must be a JSON object/array or JSON string")
    pathlib.Path(tmp_path).write_text(payload, encoding="utf-8")
    return tmp_path


def _gcs_upload(data: bytes, bucket: str, prefix: Optional[str], extension: str = ".bin") -> Dict[str, Any]:
    try:
        storage = __import__("google.cloud.storage", fromlist=["Client"])  # type: ignore
    except Exception as exc:
        raise RuntimeError("google-cloud-storage is required for gcs output") from exc

    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds_path or not os.path.exists(creds_path):
        raise RuntimeError(
            "GOOGLE_APPLICATION_CREDENTIALS must point to a readable service-account JSON file"
        )
    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCS_PROJECT")
    client = storage.Client(project=project)  # uses GOOGLE_APPLICATION_CREDENTIALS

    bucket_obj = client.bucket(bucket)
    # Генерируем имя файла с правильным расширением
    import datetime as dt
    import uuid

    ts = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    unique = uuid.uuid4().hex[:8]
    
    # Убедимся что extension начинается с точки
    if extension and not extension.startswith("."):
        extension = f".{extension}"
    
    object_name = f"{prefix or 'comfy/outputs'}/{ts}-{unique}{extension}"
    blob = bucket_obj.blob(object_name)
    
    # Определяем content_type
    content_type = _infer_mime_type(extension)
    
    # Загружаем с правильным content_type
    blob.upload_from_string(data, content_type=content_type)

    # Формируем публичный HTTPS URL
    https_url = f"https://storage.googleapis.com/{bucket}/{object_name}"

    result: Dict[str, Any] = {
        "url": https_url,
        "gcs_path": f"gs://{bucket}/{object_name}",
    }

    # Optional public-read
    if str(os.environ.get("GCS_PUBLIC", "")).strip().lower() in {"1", "true", "yes", "on"}:
        try:
            blob.acl.all().grant_read()
            blob.acl.save()
        except Exception:
            pass

    # Optional signed URL
    try:
        ttl = int(os.environ.get("GCS_SIGNED_URL_TTL", "0"))
    except ValueError:
        ttl = 0
    if ttl > 0:
        try:
            import datetime as dt

            signed = blob.generate_signed_url(expiration=dt.timedelta(seconds=ttl))
            result["signed_url"] = signed
        except Exception:
            pass

    return result


def _bool(val: Any, default: bool = False) -> bool:
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in {"1", "true", "yes", "on"}


_DEFAULT_BUILDS_ROOT = "/runpod-volume/builds"


def _builds_root() -> pathlib.Path:
    raw = os.environ.get("COMFY_BUILDS_ROOT", _DEFAULT_BUILDS_ROOT)
    return pathlib.Path(raw).expanduser()


def _prebuilt_comfy_home(version_id: str) -> pathlib.Path:
    return _builds_root() / f"comfy-{version_id}"


def _ensure_models_dir(path: pathlib.Path) -> pathlib.Path:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        log_warn(f"[serverless] не удалось создать MODELS_DIR {path}: {exc}")
    return path


def handler(event: Dict[str, Any]) -> Dict[str, Any]:  # runpod serverless handler
    # Поддерживаем как event["input"], так и event напрямую
    payload: Dict[str, Any] = event.get("input") if isinstance(event, dict) else None  # type: ignore
    if not isinstance(payload, dict):
        payload = event if isinstance(event, dict) else {}

    version_id = payload.get("version_id") or os.environ.get("COMFY_VERSION_NAME")
    if not isinstance(version_id, str) or not version_id.strip():
        log_warn("[serverless] version_id отсутствует в payload и окружении")
        return {"error": "version_id is required"}
    version_id = version_id.strip()

    request_id = event.get("requestId") if isinstance(event, dict) else None
    log_info(f"[serverless] handler start (request_id={request_id}, version_id={version_id})")

    workflow_file: Optional[str] = None
    try:
        if "workflow_url" in payload and isinstance(payload["workflow_url"], str):
            log_info("[serverless] загрузка workflow по URL")
            workflow_file = _download_to_temp(payload["workflow_url"])  # type: ignore[arg-type]
        elif "workflow" in payload:
            log_info("[serverless] запись inline workflow во временный файл")
            workflow_file = _write_json_to_temp(payload["workflow"])
        else:
            log_warn("[serverless] не передан workflow или workflow_url")
            return {"error": "workflow or workflow_url must be provided"}

        # Output options
        output_mode = (payload.get("output_mode") or os.environ.get("OUTPUT_MODE") or "gcs").strip()
        gcs_bucket = payload.get("gcs_bucket") or os.environ.get("GCS_BUCKET")
        gcs_prefix = payload.get("gcs_prefix") or os.environ.get("GCS_PREFIX", "comfy/outputs")
        verbose = _bool(payload.get("verbose"), False)

        # 1) Используем заранее подготовленное окружение из builds
        builds_root_path = _builds_root()
        if not builds_root_path.exists():
            error = f"Каталог prebuilt окружений не найден: {builds_root_path}"
            log_error(f"[serverless] {error}")
            return {"error": error}

        comfy_home_path = _prebuilt_comfy_home(version_id)
        log_info(f"[serverless] ищу prebuilt окружение: {comfy_home_path}")

        if not comfy_home_path.exists():
            error = f"Prebuilt окружение для версии '{version_id}' не найдено: {comfy_home_path}"
            log_error(f"[serverless] {error}")
            return {"error": error}

        main_py = comfy_home_path / "main.py"
        if not main_py.exists():
            error = f"ComfyUI main.py не найден в {main_py}"
            log_error(f"[serverless] {error}")
            return {"error": error}

        models_override_raw = payload.get("models_dir")
        if isinstance(models_override_raw, str) and models_override_raw.strip():
            models_dir_effective = pathlib.Path(models_override_raw).expanduser().resolve(strict=False)
            log_info(f"[serverless] MODELS_DIR переопределён из payload: {models_dir_effective}")
        else:
            env_models = os.environ.get("MODELS_DIR")
            if env_models:
                default_models = pathlib.Path(env_models).expanduser().resolve(strict=False)
            else:
                default_models = (comfy_home_path.parent / "models").resolve(strict=False)
            models_dir_effective = default_models

        models_dir_effective = _ensure_models_dir(models_dir_effective)

        cache_root = pathlib.Path(os.environ.get("COMFY_CACHE_ROOT", "")).expanduser() if os.environ.get("COMFY_CACHE_ROOT") else None
        cache_info = f", CACHE_ROOT={cache_root}" if cache_root else ""

        # Прокидываем переменные окружения для дочернего процесса
        os.environ["COMFY_HOME"] = str(comfy_home_path)
        os.environ["MODELS_DIR"] = str(models_dir_effective)

        # В serverless окружении используем системный Python, чтобы избежать проблем с portable venv
        use_system_python = os.environ.get("COMFY_USE_SYSTEM_PYTHON", "").strip().lower() in {"1", "true", "yes"}
        
        if use_system_python:
            # Используем системный Python и добавляем site-packages из venv в PYTHONPATH
            # Это решает проблему non-portable venv между разными контейнерами
            log_info("[serverless] COMFY_USE_SYSTEM_PYTHON=1 — используется системный Python контейнера")
            
            # Принудительно очищаем COMFY_PYTHON, чтобы использовать системный
            os.environ.pop("COMFY_PYTHON", None)
            
            venv_site_packages = comfy_home_path / ".venv" / "lib"
            if venv_site_packages.exists():
                # Находим python3.x директорию в lib
                python_dirs = list(venv_site_packages.glob("python3.*"))
                if python_dirs:
                    site_packages = python_dirs[0] / "site-packages"
                    if site_packages.exists():
                        current_path = os.environ.get("PYTHONPATH", "")
                        new_path = f"{site_packages}:{current_path}" if current_path else str(site_packages)
                        os.environ["PYTHONPATH"] = new_path
                        log_info(f"[serverless] PYTHONPATH={site_packages}")
                    else:
                        log_warn(f"[serverless] site-packages не найден: {site_packages}")
                else:
                    log_warn(f"[serverless] python3.* директория не найдена в {venv_site_packages}")
            else:
                log_warn(f"[serverless] venv не найден: {venv_site_packages}")
        elif "COMFY_PYTHON" not in os.environ:
            # Fallback: используем venv Python если он есть
            venv_python = comfy_home_path / ".venv" / "bin" / "python"
            if venv_python.exists() and os.access(venv_python, os.X_OK):
                os.environ["COMFY_PYTHON"] = str(venv_python)
                log_info(f"[serverless] используется venv Python: {venv_python}")
            else:
                log_warn(
                    f"[serverless] COMFY_PYTHON не задан и {venv_python} не найден или неисполняем; будет использован системный python"
                )

        log_info(
            f"[serverless] готово prebuilt окружение: COMFY_HOME={comfy_home_path}, MODELS_DIR={models_dir_effective}{cache_info}"
        )

        # 2) Run workflow
        # Всегда включаем verbose для диагностики
        verbose_effective = True  # Для диагностики всегда включаем подробные логи
        
        try:
            log_info("[serverless] запуск workflow через ComfyUI")
            artifact_bytes, file_extension = run_workflow(workflow_file, str(comfy_home_path), str(models_dir_effective), verbose_effective)
        except RuntimeError as exc:
            log_error(f"[serverless] выполнение workflow завершилось с ошибкой: {exc}")
            return {"error": str(exc)}

        log_info(f"[serverless] workflow завершён, размер артефактов={len(artifact_bytes)} байт, расширение={file_extension}")
        
        # Если артефакты пустые - это ошибка
        if len(artifact_bytes) == 0:
            log_error("[serverless] workflow выполнен, но не создал никаких артефактов!")
            return {"error": "Workflow completed but produced no output artifacts"}

        # 3) Build output
        if output_mode == "base64":
            encoded = base64.b64encode(artifact_bytes).decode("utf-8")
            return {
                "version_id": version_id,
                "output_mode": "base64",
                "base64": encoded,
                "size": len(artifact_bytes),
                "extension": file_extension,
            }
        elif output_mode == "gcs":
            if not gcs_bucket:
                return {"error": "GCS bucket is required for gcs output"}
            try:
                res = _gcs_upload(
                    artifact_bytes, 
                    str(gcs_bucket), 
                    str(gcs_prefix) if gcs_prefix else None,
                    extension=file_extension
                )
                res.update({
                    "version_id": version_id,
                    "output_mode": "gcs",
                    "size": len(artifact_bytes),
                    "extension": file_extension,
                })
                return res
            except Exception as exc:
                return {"error": f"GCS upload failed: {exc}"}
        else:
            return {"error": f"Unknown output mode: {output_mode}"}
    finally:
        try:
            if workflow_file and os.path.exists(workflow_file):
                os.remove(workflow_file)
                log_info("[serverless] временный файл workflow удалён")
        except Exception:
            pass


def _start_serverless() -> None:  # pragma: no cover
    runpod.serverless.start({"handler": handler})


if __name__ == "__main__":  # pragma: no cover
    _start_serverless()


