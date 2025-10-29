#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import os
import pathlib
import tempfile
import urllib.request
import uuid
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


def _generate_unique_filename(original_filename: str, request_id: Optional[str]) -> str:
    """Генерировать уникальное имя файла: requestid_random8chars_original.ext

    Args:
        original_filename: Оригинальное имя файла (например, 'img1.png')
        request_id: ID запроса от RunPod (или None)

    Returns:
        Уникальное имя файла (например, 'req123_abc45678_img1.png')
    """
    # Получить расширение файла
    file_path = pathlib.Path(original_filename)
    name_without_ext = file_path.stem
    extension = file_path.suffix

    # Создать префикс из request_id или timestamp
    if request_id:
        prefix = str(request_id).replace("-", "")[:16]  # Ограничить длину
    else:
        import datetime as dt
        prefix = dt.datetime.utcnow().strftime("%Y%m%d%H%M%S")

    # Добавить случайные символы для уникальности
    random_part = uuid.uuid4().hex[:8]

    # Сформировать уникальное имя
    unique_name = f"{prefix}_{random_part}_{name_without_ext}{extension}"

    return unique_name


def _download_input_images(input_images: Dict[str, str], comfy_home: pathlib.Path,
                           request_id: Optional[str] = None, timeout: int = 60) -> Dict[str, str]:
    """Скачать входные изображения по URL в директорию input ComfyUI.

    Args:
        input_images: Словарь {filename: url}
        comfy_home: Путь к COMFY_HOME
        request_id: ID запроса для генерации уникальных имен
        timeout: Таймаут загрузки в секундах

    Returns:
        Словарь mapping {original_filename: unique_filename}
    """
    if not input_images:
        return {}

    input_dir = comfy_home / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    filename_mapping = {}

    for filename, url in input_images.items():
        if not isinstance(filename, str) or not filename.strip():
            log_warn(f"[serverless] пропущено изображение с некорректным именем: {filename}")
            continue

        if not isinstance(url, str) or not url.strip():
            log_warn(f"[serverless] пропущено изображение '{filename}': некорректный URL")
            continue

        # Генерировать уникальное имя файла
        original_filename = filename.strip()
        unique_filename = _generate_unique_filename(original_filename, request_id)
        target_path = input_dir / unique_filename

        try:
            log_info(f"[serverless] загрузка изображения '{original_filename}' → '{unique_filename}' из {url}")
            req = urllib.request.Request(url, headers={'User-Agent': 'RunPod-ComfyUI/1.0'})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                image_data = response.read()
                target_path.write_bytes(image_data)
                log_info(f"[serverless] изображение '{unique_filename}' сохранено ({len(image_data)} байт)")
                filename_mapping[original_filename] = unique_filename
        except Exception as exc:
            raise RuntimeError(f"Не удалось загрузить изображение '{original_filename}' из {url}: {exc}") from exc

    return filename_mapping


def _process_images_array(images_array: list, comfy_home: pathlib.Path,
                          request_id: Optional[str] = None, timeout: int = 60) -> Dict[str, str]:
    """Обработать массив images [{name, image}] где image это HTTPS URL.

    Args:
        images_array: Массив [{name: str, image: str}] где image это URL
        comfy_home: Путь к COMFY_HOME
        request_id: ID запроса для генерации уникальных имен
        timeout: Таймаут загрузки в секундах

    Returns:
        Словарь mapping {original_filename: unique_filename}
    """
    if not images_array:
        return {}

    input_dir = comfy_home / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    filename_mapping = {}

    for img_obj in images_array:
        if not isinstance(img_obj, dict):
            log_warn(f"[serverless] пропущен некорректный элемент массива images: {type(img_obj)}")
            continue

        name = img_obj.get("name")
        image_url = img_obj.get("image")

        if not isinstance(name, str) or not name.strip():
            log_warn(f"[serverless] пропущено изображение: некорректное имя")
            continue

        if not isinstance(image_url, str) or not image_url.strip():
            log_warn(f"[serverless] пропущено изображение '{name}': некорректный URL")
            continue

        # Генерировать уникальное имя файла
        original_filename = name.strip()
        unique_filename = _generate_unique_filename(original_filename, request_id)
        target_path = input_dir / unique_filename

        try:
            log_info(f"[serverless] загрузка изображения '{original_filename}' → '{unique_filename}' из {image_url}")
            req = urllib.request.Request(image_url, headers={'User-Agent': 'RunPod-ComfyUI/1.0'})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                image_data = response.read()
                target_path.write_bytes(image_data)
                log_info(f"[serverless] изображение '{unique_filename}' сохранено ({len(image_data)} байт)")
                filename_mapping[original_filename] = unique_filename
        except Exception as exc:
            raise RuntimeError(f"Не удалось загрузить изображение '{original_filename}' из {image_url}: {exc}") from exc

    return filename_mapping


def _replace_filenames_in_api_workflow(workflow_data: dict, filename_mapping: Dict[str, str]) -> int:
    """Заменить имена файлов в API формате workflow (top-level node IDs).

    Args:
        workflow_data: Workflow JSON в API формате
        filename_mapping: Словарь {original_filename: unique_filename}

    Returns:
        Количество выполненных замен
    """
    replacements_count = 0

    # Ноды которые могут содержать файлы
    file_node_types = {
        "LoadImage": "image",
        "VHS_LoadVideo": "video",
        "LoadImageMask": "image",
    }

    for node_id, node_data in workflow_data.items():
        if not isinstance(node_data, dict):
            continue

        class_type = node_data.get("class_type", "")
        inputs = node_data.get("inputs", {})

        if class_type in file_node_types:
            input_field = file_node_types[class_type]
            if input_field in inputs:
                current_filename = inputs[input_field]
                if current_filename in filename_mapping:
                    new_filename = filename_mapping[current_filename]
                    inputs[input_field] = new_filename
                    log_info(f"[workflow] API node {node_id} ({class_type}): '{current_filename}' → '{new_filename}'")
                    replacements_count += 1

    return replacements_count


def _replace_filenames_in_ui_workflow(workflow_data: dict, filename_mapping: Dict[str, str]) -> int:
    """Заменить имена файлов в UI формате workflow (nodes array).

    Args:
        workflow_data: Workflow JSON в UI формате
        filename_mapping: Словарь {original_filename: unique_filename}

    Returns:
        Количество выполненных замен
    """
    replacements_count = 0

    # Ноды которые могут содержать файлы (widgets_values[0] обычно filename)
    file_node_types = {"LoadImage", "VHS_LoadVideo", "LoadImageMask"}

    for node in workflow_data.get("nodes", []):
        if not isinstance(node, dict):
            continue

        node_type = node.get("type", "")
        widgets = node.get("widgets_values", [])

        if node_type in file_node_types and len(widgets) >= 1:
            current_filename = widgets[0]
            if isinstance(current_filename, str) and current_filename in filename_mapping:
                new_filename = filename_mapping[current_filename]
                widgets[0] = new_filename
                log_info(f"[workflow] UI node {node.get('id')} ({node_type}): '{current_filename}' → '{new_filename}'")
                replacements_count += 1

    return replacements_count


def _apply_unique_filenames_to_workflow(workflow_path: str, filename_mapping: Dict[str, str]) -> None:
    """Применить mapping уникальных имен файлов к workflow JSON.

    Args:
        workflow_path: Путь к временному файлу workflow
        filename_mapping: Словарь {original_filename: unique_filename}
    """
    if not filename_mapping:
        log_info("[workflow] filename mapping пустой, замена имен не требуется")
        return

    # Загрузить workflow JSON
    try:
        workflow_data = json.loads(pathlib.Path(workflow_path).read_text(encoding='utf-8'))
    except Exception as exc:
        raise RuntimeError(f"Не удалось прочитать workflow JSON: {exc}") from exc

    # Определить формат и выполнить замену
    if "nodes" in workflow_data:
        # UI формат
        log_info("[workflow] обнаружен UI формат workflow")
        replacements_count = _replace_filenames_in_ui_workflow(workflow_data, filename_mapping)
    else:
        # API формат
        log_info("[workflow] обнаружен API формат workflow")
        replacements_count = _replace_filenames_in_api_workflow(workflow_data, filename_mapping)

    # Записать обновленный workflow
    try:
        updated_json = json.dumps(workflow_data, ensure_ascii=False, indent=2)
        pathlib.Path(workflow_path).write_text(updated_json, encoding='utf-8')
        log_info(f"[workflow] выполнено замен имен файлов: {replacements_count}")
    except Exception as exc:
        raise RuntimeError(f"Не удалось записать обновленный workflow: {exc}") from exc


def _cleanup_directory(directory: pathlib.Path, pattern: str = "*", request_id: Optional[str] = None) -> int:
    """Удалить файлы из директории.

    Args:
        directory: Директория для очистки
        pattern: Glob pattern для файлов (default: "*" - все файлы)
        request_id: Если указан, удалять только файлы начинающиеся с request_id

    Returns:
        Количество удаленных файлов
    """
    if not directory.exists():
        return 0

    deleted_count = 0

    try:
        if request_id:
            # Удалять только файлы для конкретного request_id
            # Формат имени: requestid_randomchars_originalname.ext
            request_prefix = str(request_id).replace("-", "")[:16]
            search_pattern = f"{request_prefix}_*"
        else:
            # Удалять все файлы по pattern
            search_pattern = pattern

        for file_path in directory.glob(search_pattern):
            if file_path.is_file():
                try:
                    file_path.unlink()
                    deleted_count += 1
                except Exception as exc:
                    log_warn(f"[cleanup] не удалось удалить файл {file_path}: {exc}")
    except Exception as exc:
        log_warn(f"[cleanup] ошибка при очистке директории {directory}: {exc}")

    return deleted_count


def _gcs_upload(data: bytes, bucket: str, prefix: Optional[str], extension: str = ".bin",
                request_id: Optional[str] = None) -> Dict[str, Any]:
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

    ts = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    unique = uuid.uuid4().hex[:8]

    # Убедимся что extension начинается с точки
    if extension and not extension.startswith("."):
        extension = f".{extension}"

    # Включить request_id в имя файла если доступен
    if request_id:
        request_prefix = str(request_id).replace("-", "")[:16]
        object_name = f"{prefix or 'comfy/outputs'}/{request_prefix}_{ts}-{unique}{extension}"
    else:
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
    log_info(f"[serverless] handler start++ (request_id={request_id}, version_id={version_id})")

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

        # 1.5) Загрузить входные изображения, если они указаны
        # Поддерживаем два формата:
        # 1. input_images: Dict[str, str] - {"filename": "url"}
        # 2. images: List[Dict] - [{"name": "filename", "image": "url"}]

        filename_mapping: Dict[str, str] = {}  # Mapping original -> unique filenames

        input_images = payload.get("input_images")
        if input_images and isinstance(input_images, dict):
            log_info(f"[serverless] обнаружено {len(input_images)} входных изображений (input_images)")
            try:
                mapping = _download_input_images(input_images, comfy_home_path, request_id)
                filename_mapping.update(mapping)
                log_info(f"[serverless] создано {len(mapping)} уникальных имен файлов")
            except RuntimeError as exc:
                log_error(f"[serverless] ошибка загрузки входных изображений: {exc}")
                return {"error": str(exc)}

        images_array = payload.get("images")
        if images_array and isinstance(images_array, list):
            log_info(f"[serverless] обнаружено {len(images_array)} изображений в массиве (images)")
            try:
                mapping = _process_images_array(images_array, comfy_home_path, request_id)
                filename_mapping.update(mapping)
                log_info(f"[serverless] создано {len(mapping)} уникальных имен файлов")
            except RuntimeError as exc:
                log_error(f"[serverless] ошибка обработки images: {exc}")
                return {"error": str(exc)}

        # 1.6) Применить уникальные имена файлов к workflow
        if filename_mapping and workflow_file:
            try:
                _apply_unique_filenames_to_workflow(workflow_file, filename_mapping)
                log_info(f"[serverless] применены уникальные имена к {len(filename_mapping)} файлам в workflow")
            except Exception as exc:
                log_error(f"[serverless] ошибка замены имен в workflow: {exc}")
                return {"error": f"Не удалось обновить workflow: {exc}"}

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
                    extension=file_extension,
                    request_id=request_id
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
        # Cleanup временного файла workflow
        try:
            if workflow_file and os.path.exists(workflow_file):
                os.remove(workflow_file)
                log_info("[serverless] временный файл workflow удалён")
        except Exception:
            pass

        # Cleanup входных файлов для данного request
        try:
            if request_id and 'comfy_home_path' in locals():
                input_dir = comfy_home_path / "input"
                if input_dir.exists():
                    deleted = _cleanup_directory(input_dir, request_id=request_id)
                    if deleted > 0:
                        log_info(f"[serverless] удалено {deleted} входных файлов для request {request_id}")
        except Exception as exc:
            log_warn(f"[serverless] ошибка при cleanup входных файлов: {exc}")


def _start_serverless() -> None:  # pragma: no cover
    runpod.serverless.start({"handler": handler})


if __name__ == "__main__":  # pragma: no cover
    _start_serverless()


