# Поле python_packages в спецификации версии

## Описание

Поле `python_packages` позволяет указать дополнительные Python пакеты, которые нужно установить при развёртывании версии ComfyUI. Пакеты устанавливаются после зависимостей кастом-нод, но перед подготовкой моделей.

## Формат

`python_packages` — это опциональный список строк в формате pip requirements:

```json
{
  "schema_version": 2,
  "version_id": "my-version",
  "comfy": { ... },
  "custom_nodes": [ ... ],
  "models": [ ... ],
  "python_packages": [
    "package-name",
    "package-with-version==1.2.3",
    "package-with-range>=2.0,<3.0"
  ],
  "env": {},
  "options": {}
}
```

## Поддерживаемые форматы спецификации пакетов

-   Без версии: `"packagename"`
-   Точная версия: `"packagename==1.2.3"`
-   Минимальная версия: `"packagename>=1.0"`
-   Диапазон версий: `"packagename>=1.0,<2.0"`
-   Любой валидный формат pip requirements

## Примеры использования

### Пример 1: Wan Video с оптимизациями

```json
{
  "schema_version": 2,
  "version_id": "wan22-fast",
  "comfy": {
    "repo": "https://github.com/comfyanonymous/ComfyUI",
    "ref": "master"
  },
  "custom_nodes": [ ... ],
  "models": [ ... ],
  "python_packages": [
    "sageattention",
    "onnx",
    "onnxruntime-gpu"
  ]
}
```

### Пример 2: Flux с точными версиями

```json
{
    "python_packages": [
        "torch==2.1.0",
        "transformers>=4.35.0",
        "diffusers==0.24.0"
    ]
}
```

## Порядок установки

При выполнении `python3 scripts/version.py realize <version-id>`:

1. Клонирование ComfyUI и установка `requirements.txt` ядра
2. Клонирование кастом-нод
3. Установка `requirements.txt` каждой кастом-ноды
4. **Установка пакетов из `python_packages`** ← это новое
5. Подготовка моделей
6. Проверка зависимостей кастом-нод

## Offline режим

В offline режиме (`--offline` или `options.offline: true`) установка `python_packages` пропускается с предупреждением. Для работы в offline:

1. Предварительно установите пакеты в окружение
2. Или используйте `--wheels-dir` с локальными wheel файлами (поддержка будет добавлена)

## Проверка установки

После развёртывания можно проверить установленные пакеты:

```bash
# Если используется venv
$COMFY_HOME/.venv/bin/python -m pip list | grep sageattention

# Или через системный Python
python3 -m pip list | grep sageattention
```

## Отличия от requirements.txt кастом-нод

-   `requirements.txt` кастом-нод устанавливаются автоматически из репозитория ноды
-   `python_packages` указывается явно в спецификации версии и устанавливается глобально для всего окружения
-   `python_packages` полезен для общих зависимостей или когда нужно переопределить версию пакета

## Добавление в существующую версию

Чтобы добавить `python_packages` в существующую спецификацию:

1. Отредактируйте файл `versions/<id>.json`
2. Добавьте поле `python_packages` с нужными пакетами
3. Запустите `python3 scripts/version.py validate <id>` для проверки
4. Пересоздайте окружение:

```bash
python3 scripts/version.py delete <id>
python3 scripts/version.py realize <id>
```

## См. также

-   `docs/instructions.md` — общее руководство по спецификациям
-   `docs/tech.md` — архитектура и структура кешей
