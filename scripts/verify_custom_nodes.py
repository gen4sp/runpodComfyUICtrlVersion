#!/usr/bin/env python3
"""
Скрипт для восстановления кастом-нод из lock-файлов.

Читает resolved-lock (`/runpod-volume/cache/runpod-comfy/resolved/<id>.lock.json`) и восстанавливает custom_nodes секцию.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from rp_handler.cache import resolved_cache_dir


class LockFileVerifier:
    def __init__(self, comfy_home: str, verbose: bool = False):
        self.comfy_home = Path(comfy_home).expanduser().resolve()
        self.verbose = verbose
        self.stats = {"total": 0, "ok": 0, "updated": 0, "errors": 0}
        self.errors: List[str] = []

    def log(self, message: str, level: str = "INFO"):
        if self.verbose or level == "ERROR":
            print(f"[{level}] {message}")

    def run_git_command(self, cmd: List[str], cwd: Optional[Path] = None) -> Tuple[bool, str, str]:
        """Выполнение git команды."""
        try:
            result = subprocess.run(
                cmd, 
                cwd=cwd, 
                capture_output=True, 
                text=True, 
                check=True
            )
            return True, result.stdout, result.stderr
        except subprocess.CalledProcessError as e:
            return False, e.stdout, e.stderr

    def check_git_repo(self, target_dir: Path, expected_repo: str) -> Tuple[bool, str]:
        """Проверка существования репозитория и его origin."""
        if not target_dir.exists():
            return False, "Репозиторий не существует"
            
        if not (target_dir / ".git").exists():
            return False, "Не является git репозиторием"
            
        # Проверка origin
        success, stdout, stderr = self.run_git_command(
            ["git", "remote", "get-url", "origin"], 
            cwd=target_dir
        )
        
        if not success:
            return False, f"Ошибка получения origin: {stderr}"
            
        current_origin = stdout.strip()
        if current_origin != expected_repo:
            return False, f"Origin не совпадает: {current_origin} != {expected_repo}"
            
        return True, "OK"

    def get_current_commit(self, target_dir: Path) -> Optional[str]:
        """Получение текущего коммита."""
        success, stdout, stderr = self.run_git_command(
            ["git", "rev-parse", "HEAD"], 
            cwd=target_dir
        )
        return stdout.strip() if success else None

    def process_custom_node(self, node_data: Dict, overwrite: bool = False, install_reqs: bool = False) -> Dict:
        """Обработка одной ноды из lock-файла."""
        name = node_data["name"]
        repo = node_data["repo"]
        commit = node_data["commit"]
        path = node_data["path"]
        
        self.log(f"Обработка ноды: {name}")
        
        result = {
            "name": name,
            "status": "unknown",
            "message": "",
            "commit_before": None,
            "commit_after": None
        }
        
        try:
            # Разрешаем путь с подстановкой $COMFY_HOME
            if path.startswith("$COMFY_HOME"):
                target_dir = Path(path.replace("$COMFY_HOME", str(self.comfy_home)))
            else:
                target_dir = Path(path)
            
            target_dir = target_dir.expanduser().resolve()
            self.log(f"Целевая директория: {target_dir}")
            
            # Проверка существования репозитория
            repo_exists, repo_msg = self.check_git_repo(target_dir, repo)
            
            if repo_exists:
                # Репозиторий существует, проверяем коммит
                current_commit = self.get_current_commit(target_dir)
                result["commit_before"] = current_commit
                
                if current_commit:
                    if current_commit == commit:
                        result["status"] = "ok"
                        result["message"] = "Уже на нужном коммите"
                        result["commit_after"] = current_commit
                    else:
                        # Переключаемся на нужный коммит
                        success, stdout, stderr = self.run_git_command(
                            ["git", "fetch", "origin"], 
                            cwd=target_dir
                        )
                        if not success:
                            result["status"] = "error"
                            result["message"] = f"Ошибка fetch: {stderr}"
                            return result
                        
                        success, stdout, stderr = self.run_git_command(
                            ["git", "checkout", commit], 
                            cwd=target_dir
                        )
                        if success:
                            result["status"] = "updated"
                            result["message"] = f"Обновлен с {current_commit[:8]} на {commit[:8]}"
                            result["commit_after"] = commit
                        else:
                            result["status"] = "error"
                            result["message"] = f"Ошибка checkout: {stderr}"
                else:
                    result["status"] = "error"
                    result["message"] = "Не удалось получить текущий коммит"
            else:
                # Репозиторий не существует или неправильный origin
                if overwrite and target_dir.exists():
                    self.log(f"Удаление существующей директории: {target_dir}")
                    import shutil
                    shutil.rmtree(target_dir)
                
                # Клонируем репозиторий
                target_dir.parent.mkdir(parents=True, exist_ok=True)
                
                success, stdout, stderr = self.run_git_command(
                    ["git", "clone", repo, str(target_dir)]
                )
                
                if not success:
                    result["status"] = "error"
                    result["message"] = f"Ошибка клонирования: {stderr}"
                    return result
                
                # Переключаемся на нужный коммит
                success, stdout, stderr = self.run_git_command(
                    ["git", "checkout", commit], 
                    cwd=target_dir
                )
                
                if not success:
                    result["status"] = "error"
                    result["message"] = f"Ошибка checkout на '{commit}': {stderr}"
                    return result
                
                result["status"] = "updated"
                result["message"] = f"Клонирован и переключен на {commit[:8]}"
                result["commit_after"] = self.get_current_commit(target_dir)
            
            # Установка requirements.txt если нужно
            if install_reqs:
                self.install_requirements(target_dir, result)
                
        except Exception as e:
            result["status"] = "error"
            result["message"] = f"Исключение: {str(e)}"
            
        return result

    def install_requirements(self, target_dir: Path, result: Dict):
        """Установка requirements.txt."""
        req_file = target_dir / "requirements.txt"
        if not req_file.exists():
            self.log(f"requirements.txt не найден в {target_dir}")
            return
            
        # Определяем виртуальное окружение
        venv_path = self.comfy_home / ".venv"
        if venv_path.exists():
            pip_cmd = str(venv_path / "bin" / "pip")
            self.log(f"Используем venv: {pip_cmd}")
        else:
            pip_cmd = "pip"
            self.log("Используем системный pip")
        
        # Устанавливаем requirements
        success, stdout, stderr = self.run_git_command(
            [pip_cmd, "install", "-r", str(req_file)], 
            cwd=target_dir
        )
        
        if success:
            self.log(f"Requirements установлены для {target_dir}")
        else:
            self.log(f"Ошибка установки requirements: {stderr}", "ERROR")
            if result["status"] == "ok":
                result["status"] = "warning"
                result["message"] += f" (ошибка requirements: {stderr})"

    def process_lock_file(self, lock_file: Path, overwrite: bool = False, install_reqs: bool = False) -> List[Dict]:
        """Обработка lock-файла."""
        self.log(f"Обработка lock-файла: {lock_file}")
        
        try:
            with open(lock_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            self.errors.append(f"Ошибка чтения {lock_file}: {e}")
            return []
        
        if "custom_nodes" not in data:
            self.log(f"Секция 'custom_nodes' не найдена в {lock_file}")
            return []
        
        custom_nodes = data["custom_nodes"]
        if not isinstance(custom_nodes, list):
            self.errors.append(f"{lock_file}: custom_nodes должен быть массивом")
            return []
        
        results = []
        for node_data in custom_nodes:
            if not isinstance(node_data, dict):
                self.errors.append(f"Некорректные данные ноды в {lock_file}")
                continue
                
            required_fields = ["name", "repo", "commit", "path"]
            if not all(field in node_data for field in required_fields):
                self.errors.append(f"Отсутствуют обязательные поля в ноде {node_data.get('name', 'unknown')}")
                continue
            
            result = self.process_custom_node(node_data, overwrite, install_reqs)
            results.append(result)
            self.stats["total"] += 1
            
            if result["status"] == "ok":
                self.stats["ok"] += 1
            elif result["status"] == "updated":
                self.stats["updated"] += 1
            else:
                self.stats["errors"] += 1
                self.errors.append(f"{result['name']}: {result['message']}")
        
        return results

    def print_summary(self):
        """Вывод итоговой статистики."""
        print("\n" + "="*50)
        print("ИТОГОВАЯ СТАТИСТИКА")
        print("="*50)
        print(f"Всего нод: {self.stats['total']}")
        print(f"OK: {self.stats['ok']}")
        print(f"Обновлено: {self.stats['updated']}")
        print(f"Ошибки: {self.stats['errors']}")
        
        if self.errors:
            print("\nОШИБКИ:")
            for error in self.errors:
                print(f"  - {error}")


def main():
    parser = argparse.ArgumentParser(description="Восстановление кастом-нод из lock-файлов")
    parser.add_argument("--lock-files", nargs="+", help="Lock файлы для обработки")
    parser.add_argument("--comfy-home", default=os.environ.get("COMFY_HOME", "./comfy"), 
                       help="Путь к ComfyUI (по умолчанию: $COMFY_HOME или ./comfy)")
    parser.add_argument("--overwrite", action="store_true", 
                       help="Перезаписать существующие репозитории")
    parser.add_argument("--install-reqs", action="store_true", 
                       help="Установить requirements.txt")
    parser.add_argument("--workers", type=int, default=4, 
                       help="Количество параллельных потоков")
    parser.add_argument("--verbose", action="store_true", 
                       help="Подробный вывод")
    
    args = parser.parse_args()
    
    # Определяем lock файлы
    if args.lock_files:
        lock_files = [Path(f) for f in args.lock_files]
    else:
        resolved_dir = resolved_cache_dir()
        lock_files = list(resolved_dir.glob("*.lock.json"))

    if not lock_files:
        print("Ошибка: не найдено resolved-lock файлов. Укажите --lock-files или выполните scripts/version.py validate")
        sys.exit(1)
    
    verifier = LockFileVerifier(args.comfy_home, args.verbose)
    
    # Обработка файлов
    all_results = []
    for lock_file in lock_files:
        results = verifier.process_lock_file(
            lock_file, 
            overwrite=args.overwrite, 
            install_reqs=args.install_reqs
        )
        all_results.extend(results)
    
    verifier.print_summary()
    
    # Возвращаем код ошибки если были проблемы
    if verifier.stats["errors"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
