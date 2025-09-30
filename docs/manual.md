## ComfyUI Version Control — Manual

```js
//remove
rm -rf /runpod-volume/builds/comfy-wan22-fast/
// create
...

// realize
python ./scripts/version.py realize wan22-fast --target /runpod-volume/builds/comfy-wan22-fast/
```

Минимальный гид по работе со спецификациями `versions/<id>.json` и единым CLI `scripts/version.py`.

### Предусловия

-   Python 3.11+
-   Git
-   Доступ к интернету для первичного скачивания
-   (Опционально) Docker/RunPod для развёртывания

### Основные сущности

-   `versions/<id>.json` — описание версии (ядро, кастом-ноды, модели, опции).
-   `COMFY_HOME` — каталог развёрнутой версии (если переменная не задана, внутри образа используется `/runpod-volume/ComfyUI`, локально — `~/comfy-<id>`, на RunPod volume — `/runpod-volume/builds/comfy-<id>`).
-   `MODELS_DIR` — каталог моделей. По умолчанию общий кеш `COMFY_CACHE_ROOT/models`.

### Шаги

1. **Создание спецификации**

    ```bash
    python3 scripts/version.py create demo \
      --repo https://github.com/comfyanonymous/ComfyUI@master \
      --nodes custom_nodes.json \
      --models models.json
    ```

    Получится `versions/demo.json` со всеми параметрами.

2. **Проверка и резолвинг**

    ```bash
    python3 scripts/version.py validate demo
    ```

    Команда резолвит SHA, сохраняет `/runpod-volume/cache/runpod-comfy/resolved/demo.lock.json` и печатает план.

3. **Развёртывание окружения**

    ```bash
    python3 scripts/version.py realize demo
    ```

    Скрипт клонирует ComfyUI и кастом-ноды в кеш, создаёт симлинки моделей, устанавливает `requirements.txt`. Для Pod с volume задайте `COMFY_HOME=/runpod-volume/builds/comfy-demo` или используйте `--target /runpod-volume/builds/comfy-demo`.

4. **Запуск UI**

    ```bash
    python3 scripts/version.py run-ui demo --port 9000
    ```

    По умолчанию слушает `0.0.0.0:8188`. Любые аргументы после `--` передаются напрямую `ComfyUI/main.py`.

5. **Запуск handler (headless)**

    ```bash
    python3 scripts/version.py run-handler wan22-fast \
      --workflow workflows/minimal.json \
      --output base64 --out-file result.b64
    ```

    Handler сам резолвит версию, использует общий кеш и возвращает результат (base64 или загрузка в GCS).

6. **Управление версиями**

    ```bash
    python3 scripts/version.py clone demo demo-copy
    python3 scripts/version.py delete demo --remove-spec
    ```

### Полезные опции CLI

-   `--offline` — не обращаться к сети (если нужные кеши уже существуют).
-   `--models-dir` — указать явный каталог моделей.
-   `--wheels-dir` — каталог с wheel-ами для оффлайн-установки зависимостей.
-   `--extra-args -- --no-auto-launch` — передать флаги напрямую ComfyUI.

### Переменные окружения

-   `COMFY_HOME`, `MODELS_DIR` — переопределение стандартных путей.
-   `COMFY_CACHE_ROOT` — базовый каталог кеша (`comfy`, `custom_nodes`, `models`, `resolved`).
-   `COMFY_OFFLINE` — заставляет resolver/realizer работать без сети.
-   `HF_TOKEN`, `CIVITAI_TOKEN` — токены для скачивания моделей.

### Дальше

-   `docs/instructions.md` — подробные сценарии RunPod/Docker.
-   `docs/runpod.md` — специфичные настройки RunPod.
-   `docs/smoketest.md` — чек-лист проверки.
