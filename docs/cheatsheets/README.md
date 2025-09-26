# ComfyUI Version Control - Cheatsheets

Быстрые команды для всех этапов работы с управлением версиями ComfyUI.

## 📋 Содержание

### 🚀 Основные этапы

1. **[Инициализация ComfyUI](init.md)** - Установка и настройка базового ComfyUI
2. **[Создание версии](create_version.md)** - Формирование спецификации и подготовка `versions/<id>.json`
3. **[Реализация версии](realize_version.md)** - Развёртка версии по новой схеме (`--version-id`/`--spec`)
4. **[Установка моделей](models.md)** - Скачивание и верификация моделей
5. **[Кастом ноды и зависимости](custom_nodes_deps.md)** - Установка расширений и зависимостей
6. **[Запуск на RunPod](runpod_local.md)** - Локальный/Pods запуск handler

### 🎯 Специализированные сценарии

6. **[Базовые версии](base_version.md)** - Создание минимальных версий для форка
7. **[Запуск на RunPod](runpod_local.md)** - Локальный запуск версий вне Docker
8. **[Ручная настройка и упаковка](manual_setup_packaging.md)** - Полный цикл настройки и тестирования

## 🎨 Цветовая кодировка команд

-   🟢 **Зеленый** - основные команды для копирования
-   🔵 **Синий** - информационные команды
-   🟡 **Желтый** - команды требующие настройки переменных
-   🔴 **Красный** - команды требующие осторожности

## 📝 Использование

Каждая команда в cheatsheets готова к копированию и исполнению. Большинство команд содержат:

-   Переменные окружения в начале
-   Основную команду
-   Параметры и опции
-   Примеры вывода

## 🔧 Быстрые ссылки

### Быстрый старт новой версии

```bash
# 1. Инициализация
export COMFY_HOME="$HOME/comfy"
./scripts/init_comfyui.sh --install-torch auto

# 2. Создание версии
python3 scripts/create_version.py --name my-version --comfy-repo https://github.com/comfyanonymous/ComfyUI

# 3. Реализация версии из JSON (создаст изолированный COMFY_HOME)
python3 scripts/realize_version.py --version-id "my-version"
```

### Запуск на RunPod

```bash
# Установка переменных
export COMFY_HOME="/runpod-volume/comfy"
export COMFY_VERSION_NAME="my-version"

# Запуск handler
./scripts/run_handler_local.sh --version-id my-version --workflow workflows/minimal.json --output base64
```

### Ручная настройка версии

```bash
# Инициализация
./scripts/init_comfyui.sh --path "$HOME/comfy-manual" --install-torch auto

# Установка компонентов
cd "$HOME/comfy-manual"
source .venv/bin/activate
git clone https://github.com/city96/ComfyUI-GGUF custom_nodes/ComfyUI-GGUF

# Создание lock
python3 ~/runpodComfyuiVersionControl/scripts/create_version.py --name "manual-v1" --comfy-path ComfyUI --venv .venv --pretty
```

## 🏷️ Теги и категории

-   **#init** - инициализация
-   **#version** - управление версиями
-   **#models** - работа с моделями
-   **#custom-nodes** - кастом ноды
-   **#runpod** - запуск на RunPod
-   **#manual** - ручная настройка
-   **#base** - базовые версии

## 📊 Структура проекта

```
cheatsheets/
├── README.md             # Этот файл
├── init.md               # Инициализация
├── create_version.md     # Создание версий (schema v2)
├── realize_version.md    # Реализация версии по спецификации
├── models.md             # Модели и MODELS_DIR
├── custom_nodes_deps.md  # Кастом ноды и зависимости
├── base_version.md       # Базовые версии
├── runpod_local.md       # Запуск на RunPod
└── manual_setup_packaging.md # Ручная настройка
```
