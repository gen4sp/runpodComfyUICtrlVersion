#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import time
import urllib.request
from typing import Deque, Dict, List, Optional, Tuple, IO
import threading
from collections import deque

from .utils import log_info, log_warn, log_error, run_command, validate_required_path


class ComfyUIWorkflowRunner:
    """Раннер для выполнения ComfyUI workflow в headless режиме."""

    def __init__(self, comfy_home: str, models_dir: str, verbose: bool = False):
        self.comfy_home = pathlib.Path(comfy_home)
        self.models_dir = pathlib.Path(models_dir)
        self.verbose = verbose
        self.process: Optional[subprocess.Popen] = None
        self.api_url = "http://127.0.0.1:8188"
        self._log_tail: deque[str] = deque(maxlen=20)
        self._reader_threads: List[threading.Thread] = []
        self._reader_stop = threading.Event()
        
    def _prepare_directories(self) -> None:
        """Подготовить необходимые директории."""
        # Создаем основные директории ComfyUI
        dirs_to_create = [
            self.comfy_home / "models",
            self.comfy_home / "input",
            self.comfy_home / "output",
            self.comfy_home / "temp",
        ]
        
        for dir_path in dirs_to_create:
            dir_path.mkdir(parents=True, exist_ok=True)
            if self.verbose:
                log_info(f"[workflow] подготовлена директория: {dir_path}")
    
    def _create_process(self, cmd: List[str], env: Dict[str, str]) -> subprocess.Popen:
        return subprocess.Popen(
            cmd,
            cwd=str(self.comfy_home),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def _spawn_reader(self, stream: IO[str], label: str) -> None:
        def reader() -> None:
            while not self._reader_stop.is_set():
                line = stream.readline()
                if not line:
                    if self.process and self.process.poll() is not None:
                        break
                    time.sleep(0.1)
                    continue
                text = line.rstrip()
                if text:
                    log_info(f"[workflow:{label}] {text}")
                    self._log_tail.append(text)

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        self._reader_threads.append(thread)

    def _stop_readers(self) -> None:
        self._reader_stop.set()
        for thread in self._reader_threads:
            thread.join(timeout=1.0)
        self._reader_threads.clear()
        self._reader_stop.clear()

    def _start_comfyui(self) -> None:
        """Запустить ComfyUI в headless режиме."""
        main_script = self.comfy_home / "main.py"
        if not main_script.exists():
            raise RuntimeError(f"ComfyUI main.py not found at {main_script}")
        
        # Настройка окружения для ComfyUI
        env = os.environ.copy()
        env["COMFY_HOME"] = str(self.comfy_home)
        env["MODELS_DIR"] = str(self.models_dir)
        
        python_path = env.get("COMFY_PYTHON")
        if not python_path:
            # Если COMFY_USE_SYSTEM_PYTHON установлен, используем системный Python
            use_system_python = env.get("COMFY_USE_SYSTEM_PYTHON", "").strip().lower() in {"1", "true", "yes"}
            if use_system_python:
                python_path = "python3"
                # PYTHONPATH уже должен быть установлен в serverless.py
                if self.verbose:
                    log_info(f"[workflow] используется системный Python (python3), PYTHONPATH={env.get('PYTHONPATH', 'не задан')}")
            else:
                venv_path = self.comfy_home / ".venv" / "bin" / "python"
                if venv_path.exists():
                    python_path = str(venv_path)
                    if self.verbose:
                        log_info(f"[workflow] используется venv Python: {python_path}")
                else:
                    python_path = "python"
                    if self.verbose:
                        log_info(f"[workflow] venv не найден, используется системный python")
        else:
            if self.verbose:
                log_info(f"[workflow] используется COMFY_PYTHON: {python_path}")

        cmd = [
            python_path, str(main_script),
            "--listen", "127.0.0.1",
            "--port", "8188",
            "--disable-auto-launch"
        ]
        
        if self.verbose:
            log_info(f"[workflow] старт ComfyUI: {' '.join(cmd)}")
            log_info(f"[workflow] COMFY_HOME={env.get('COMFY_HOME')}")
            log_info(f"[workflow] MODELS_DIR={env.get('MODELS_DIR')}")
            if env.get('PYTHONPATH'):
                log_info(f"[workflow] PYTHONPATH={env.get('PYTHONPATH')}")
        
        self.process = self._create_process(cmd, env)
        assert self.process.stdout and self.process.stderr
        self._spawn_reader(self.process.stdout, "stdout")
        self._spawn_reader(self.process.stderr, "stderr")
    
    def _wait_for_comfyui(self, timeout: int = 60) -> None:
        """Дождаться запуска ComfyUI."""
        start_time = time.time()
        
        # Проверяем, что процесс не упал
        if self.process and self.process.poll() is not None:
            raise RuntimeError(f"ComfyUI процесс завершился преждевременно. Последние строки: {' | '.join(list(self._log_tail))}")
        
        while time.time() - start_time < timeout:
            # Проверяем, что процесс всё ещё работает
            if self.process and self.process.poll() is not None:
                raise RuntimeError(f"ComfyUI процесс упал во время запуска. Последние строки: {' | '.join(list(self._log_tail))}")
            
            try:
                # Пробуем несколько эндпоинтов для проверки готовности
                for endpoint in ["/", "/queue"]:
                    try:
                        with urllib.request.urlopen(f"{self.api_url}{endpoint}", timeout=2) as response:
                            if response.status == 200:
                                if self.verbose:
                                    log_info(f"[workflow] ComfyUI готов к приёму запросов (проверен {endpoint})")
                                return
                    except (urllib.error.URLError, urllib.error.HTTPError):
                        continue
            except OSError:
                pass
            
            if self.verbose and int(time.time() - start_time) % 5 == 0:  # Логируем каждые 5 секунд
                elapsed = int(time.time() - start_time)
                log_info(f"[workflow] ComfyUI ещё не готов (прошло {elapsed}/{timeout} сек)")
            
            time.sleep(1)
        
        raise RuntimeError(
            f"ComfyUI failed to start within {timeout} seconds. Последние строки: {' | '.join(list(self._log_tail))}"
        )
    
    def _submit_workflow(self, workflow_data: Dict) -> str:
        """Отправить workflow в ComfyUI и получить prompt_id."""
        prompt_data = {
            "prompt": workflow_data,
            "client_id": "runpod_handler"
        }
        
        data = json.dumps(prompt_data).encode('utf-8')
        req = urllib.request.Request(
            f"{self.api_url}/prompt",
            data=data,
            headers={'Content-Type': 'application/json'}
        )
        
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
            if 'prompt_id' not in result:
                raise RuntimeError(f"Failed to submit workflow: {result}")
            return result['prompt_id']
    
    def _wait_for_completion(self, prompt_id: str, timeout: int = 300) -> List[Dict]:
        """Дождаться завершения workflow и получить результаты."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                with urllib.request.urlopen(f"{self.api_url}/history/{prompt_id}") as response:
                    history = json.loads(response.read().decode('utf-8'))
                    if prompt_id in history:
                        status = history[prompt_id].get('status', {})
                        if status.get('status_str') == 'success':
                            if self.verbose:
                                log_info("[workflow] статус: success")
                            return status.get('outputs', [])
                        elif status.get('status_str') == 'error':
                            error_msg = status.get('status_message', 'Unknown error')
                            raise RuntimeError(f"Workflow failed: {error_msg}")
                        else:
                            if self.verbose:
                                log_info(f"[workflow] статус: {status.get('status_str')} :: {status.get('status_message')}")
            except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError) as exc:
                if self.verbose:
                    log_info(f"[workflow] ожидание завершения: нет данных ({exc})")
                pass
            time.sleep(2)
        
        raise RuntimeError(f"Workflow did not complete within {timeout} seconds")
    
    def _collect_artifacts(self, outputs: List[Dict]) -> bytes:
        """Собрать артефакты из результатов workflow."""
        artifacts = []
        
        for output in outputs:
            for node_id, node_output in output.items():
                if 'images' in node_output:
                    for image_info in node_output['images']:
                        filename = image_info.get('filename')
                        if filename:
                            image_path = self.comfy_home / "output" / filename
                            if image_path.exists():
                                artifacts.append(image_path.read_bytes())
                                if self.verbose:
                                    log_info(f"[workflow] найден артефакт: {filename}")
        
        if not artifacts:
            log_warn("No artifacts found in workflow output")
            return b""
        
        # Объединяем все артефакты в один байтовый поток
        return b"".join(artifacts)
    
    def run_workflow(self, workflow_path: str) -> bytes:
        """Выполнить workflow и вернуть артефакты."""
        try:
            # 1. Подготовить директории
            self._prepare_directories()
            
            # 2. Запустить ComfyUI
            if self.verbose:
                log_info("[workflow] подготовка запуска ComfyUI")
            self._start_comfyui()
            self._wait_for_comfyui()
            
            # 3. Загрузить и отправить workflow
            workflow_data = json.loads(pathlib.Path(workflow_path).read_text(encoding='utf-8'))
            prompt_id = self._submit_workflow(workflow_data)
            
            if self.verbose:
                log_info(f"[workflow] workflow отправлен, prompt_id={prompt_id}")
            
            # 4. Дождаться завершения
            outputs = self._wait_for_completion(prompt_id)
            
            # 5. Собрать артефакты
            artifacts = self._collect_artifacts(outputs)
            
            if self.verbose:
                log_info(f"[workflow] артефакты собраны: {len(artifacts)} байт")

            return artifacts
            
        finally:
            self._stop_readers()
            # Остановить ComfyUI
            if self.process:
                self.process.terminate()
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
                if self.verbose:
                    log_info("[workflow] процесс ComfyUI остановлен")


def run_workflow(workflow_path: str, comfy_home: str, models_dir: str, verbose: bool = False) -> bytes:
    """Удобная функция для запуска workflow."""
    runner = ComfyUIWorkflowRunner(comfy_home, models_dir, verbose)
    return runner.run_workflow(workflow_path)
