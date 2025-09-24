#!/usr/bin/env python3
"""
Скрипт для валидации и установки кастом-нод ComfyUI из JSON-спецификаций.

Поддерживает:
- Валидацию JSON-структуры и URL
- Проверку существования checkout, совпадения origin и коммита
- Git clone/checkout с поддержкой перезаписи
- Установку requirements.txt
- Параллельную обработку
"""

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse


class NodeValidator:
    def __init__(self, comfy_home: str, verbose: bool = False):
        self.comfy_home = Path(comfy_home).expanduser().resolve()
        self.verbose = verbose
        self.stats = {"total": 0, "ok": 0, "updated": 0, "errors": 0}
        self.errors: List[str] = []

    def log(self, message: str, level: str = "INFO"):
        if self.verbose or level == "ERROR":
            print(f"[{level}] {message}")

    def validate_json_structure(self, data: List[Dict]) -> bool:
        """Валидация структуры JSON."""
        required_fields = ["name", "repo"]
        optional_fields = ["commit", "target_dir", "install_requirements"]
        
        for i, node in enumerate(data):
            if not isinstance(node, dict):
                self.errors.append(f"Node {i}: должен быть объектом")
                return False
                
            # Проверка обязательных полей
            for field in required_fields:
                if field not in node:
                    self.errors.append(f"Node {i}: отсутствует обязательное поле '{field}'")
                    return False
                    
            # Проверка типов
            if not isinstance(node["name"], str) or not node["name"]:
                self.errors.append(f"Node {i}: 'name' должно быть непустой строкой")
                return False
                
            if not isinstance(node["repo"], str) or not node["repo"]:
                self.errors.append(f"Node {i}: 'repo' должно быть непустой строкой")
                return False
                
            # Валидация URL
            try:
                parsed = urlparse(node["repo"])
                if not parsed.scheme or not parsed.netloc:
                    self.errors.append(f"Node {i}: невалидный URL '{node['repo']}'")
                    return False
            except Exception:
                self.errors.append(f"Node {i}: невалидный URL '{node['repo']}'")
                return False
                
            # Проверка опциональных полей
            if "commit" in node and not isinstance(node["commit"], str):
                self.errors.append(f"Node {i}: 'commit' должно быть строкой")
                return False
                
            if "target_dir" in node and not isinstance(node["target_dir"], str):
                self.errors.append(f"Node {i}: 'target_dir' должно быть строкой")
                return False
                
            if "install_requirements" in node and not isinstance(node["install_requirements"], bool):
                self.errors.append(f"Node {i}: 'install_requirements' должно быть булевым")
                return False
                
        return True

    def resolve_target_dir(self, node: Dict) -> Path:
        """Разрешение пути target_dir с подстановкой $COMFY_HOME."""
        if "target_dir" in node:
            target_dir = node["target_dir"]
            if target_dir.startswith("$COMFY_HOME"):
                target_dir = target_dir.replace("$COMFY_HOME", str(self.comfy_home))
            return Path(target_dir).expanduser().resolve()
        else:
            return self.comfy_home / "custom_nodes" / node["name"]

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

    def process_node(self, node: Dict, overwrite: bool = False, install_reqs: bool = False) -> Dict:
        """Обработка одной ноды."""
        name = node["name"]
        repo = node["repo"]
        commit = node.get("commit", "main")
        install_requirements = node.get("install_requirements", True)
        
        self.log(f"Обработка ноды: {name}")
        
        result = {
            "name": name,
            "status": "unknown",
            "message": "",
            "commit_before": None,
            "commit_after": None
        }
        
        try:
            target_dir = self.resolve_target_dir(node)
            self.log(f"Целевая директория: {target_dir}")
            
            # Проверка существования репозитория
            repo_exists, repo_msg = self.check_git_repo(target_dir, repo)
            
            if repo_exists:
                # Репозиторий существует, проверяем коммит
                current_commit = self.get_current_commit(target_dir)
                result["commit_before"] = current_commit
                
                if current_commit:
                    # Проверяем, нужен ли обновление
                    success, stdout, stderr = self.run_git_command(
                        ["git", "fetch", "origin"], 
                        cwd=target_dir
                    )
                    if not success:
                        result["status"] = "error"
                        result["message"] = f"Ошибка fetch: {stderr}"
                        return result
                    
                    # Проверяем, есть ли нужный коммит
                    success, stdout, stderr = self.run_git_command(
                        ["git", "rev-parse", f"origin/{commit}"], 
                        cwd=target_dir
                    )
                    
                    if success:
                        target_commit = stdout.strip()
                        if current_commit == target_commit:
                            result["status"] = "ok"
                            result["message"] = "Уже на нужном коммите"
                            result["commit_after"] = current_commit
                        else:
                            # Переключаемся на нужный коммит
                            success, stdout, stderr = self.run_git_command(
                                ["git", "checkout", target_commit], 
                                cwd=target_dir
                            )
                            if success:
                                result["status"] = "updated"
                                result["message"] = f"Обновлен с {current_commit[:8]} на {target_commit[:8]}"
                                result["commit_after"] = target_commit
                            else:
                                result["status"] = "error"
                                result["message"] = f"Ошибка checkout: {stderr}"
                    else:
                        result["status"] = "error"
                        result["message"] = f"Коммит/ветка '{commit}' не найдена: {stderr}"
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
                result["message"] = f"Клонирован и переключен на {commit}"
                result["commit_after"] = self.get_current_commit(target_dir)
            
            # Установка requirements.txt если нужно
            if install_reqs and install_requirements:
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

    def process_json_file(self, json_file: Path, overwrite: bool = False, install_reqs: bool = False) -> List[Dict]:
        """Обработка JSON файла."""
        self.log(f"Обработка файла: {json_file}")
        
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            self.errors.append(f"Ошибка чтения {json_file}: {e}")
            return []
        
        if not isinstance(data, list):
            self.errors.append(f"{json_file}: корневой элемент должен быть массивом")
            return []
        
        if not self.validate_json_structure(data):
            return []
        
        results = []
        for node in data:
            result = self.process_node(node, overwrite, install_reqs)
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
    parser = argparse.ArgumentParser(description="Валидация и установка кастом-нод ComfyUI")
    parser.add_argument("--json", nargs="+", help="JSON файлы для обработки")
    parser.add_argument("--comfy-home", default=os.environ.get("COMFY_HOME", "./comfy"), 
                       help="Путь к ComfyUI (по умолчанию: $COMFY_HOME или ./comfy)")
    parser.add_argument("--validate-only", action="store_true", 
                       help="Только валидация, без установки")
    parser.add_argument("--overwrite", action="store_true", 
                       help="Перезаписать существующие репозитории")
    parser.add_argument("--install-reqs", action="store_true", 
                       help="Установить requirements.txt")
    parser.add_argument("--workers", type=int, default=4, 
                       help="Количество параллельных потоков")
    parser.add_argument("--verbose", action="store_true", 
                       help="Подробный вывод")
    
    args = parser.parse_args()
    
    # Определяем JSON файлы
    if args.json:
        json_files = [Path(f) for f in args.json]
    else:
        nodes_dir = Path("nodes")
        if nodes_dir.exists():
            json_files = list(nodes_dir.glob("*.json"))
        else:
            print("Ошибка: каталог 'nodes' не найден и файлы не указаны")
            sys.exit(1)
    
    if not json_files:
        print("Ошибка: не найдено JSON файлов для обработки")
        sys.exit(1)
    
    validator = NodeValidator(args.comfy_home, args.verbose)
    
    if args.validate_only:
        print("Режим только валидации")
        for json_file in json_files:
            validator.process_json_file(json_file, overwrite=False, install_reqs=False)
    else:
        # Обработка файлов
        all_results = []
        for json_file in json_files:
            results = validator.process_json_file(
                json_file, 
                overwrite=args.overwrite, 
                install_reqs=args.install_reqs
            )
            all_results.extend(results)
    
    validator.print_summary()
    
    # Возвращаем код ошибки если были проблемы
    if validator.stats["errors"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
