## RunPod ComfyUI Version Control

Набор инструментов для описания и воспроизведения версий ComfyUI. Каждая версия задаётся единственным файлом `versions/<id>.json`, где фиксируются коммит ядра, кастом-ноды и модели. Скрипты заботятся об установке зависимостей, создании ссылок на модели и запуске UI/handler в нужном окружении. Общие кеши используются повторно между версиями, поэтому место на диске расходуется экономно.

### Ключевые возможности

-   **Единый источник правды** — JSON-спецификация schema v2. Никаких lock-файлов и отдельного описания зависимостей.
-   **Общие кеши** — репозитории ComfyUI и кастом-нод клонируются в `COMFY_CACHE_ROOT`, модели скачиваются один раз и линковаются символическими ссылками.
-   **Универсальный CLI** `scripts/version.py` — создание, проверка, развёртывание, запуск UI, запуск handler, клонирование и удаление версий.
-   **Handler и UI из одной команды** — достаточно указать `--version-id`, остальные пути рассчитываются автоматически.
-   **Документация и тесты** — обновлены под schema v2 и новые команды.

### Happy path

1. Создайте описание версии:

    ```bash
    python3 scripts/version.py create my-version \
      --repo https://github.com/comfyanonymous/ComfyUI@master \
      --nodes custom_nodes.json \
      --models models.json
    ```

2. Проверьте, что спецификация корректно резолвится и сохраните lock в кеше:

    ```bash
    python3 scripts/version.py validate my-version
    ```

3. Разверните окружение (внутри образа по умолчанию `/workspace/ComfyUI`, локально `~/comfy-<id>`):

    ```bash
    COMFY_HOME=~/comfy-my-version python3 scripts/version.py realize my-version
    ```

4. Запустите UI или handler:

    ```bash
    # UI на указанном порту
    python3 scripts/version.py run-ui my-version --port 9000

    # headless handler
    python3 scripts/version.py run-handler my-version \
      --workflow workflows/demo.json --output base64 --out-file result.b64
    ```

5. Управляйте версиями:

    ```bash
    python3 scripts/version.py clone my-version my-version-copy
    python3 scripts/version.py delete my-version --remove-spec
    ```

### Команды CLI

| Команда       | Назначение                                                             |
| ------------- | ---------------------------------------------------------------------- |
| `create`      | Сформировать `versions/<id>.json` из параметров CLI или файлов         |
| `validate`    | Проверить spec, зафиксировать SHA и сохранить resolved-lock в кеше     |
| `realize`     | Развернуть ComfyUI и подготовить симлинки моделей в указанном каталоге |
| `run-ui`      | Запустить ComfyUI UI из версии (устанавливает зависимости, берёт кеши) |
| `run-handler` | Выполнить workflow через serverless handler интерфейс                  |
| `clone`       | Скопировать spec под новым идентификатором                             |
| `delete`      | Удалить подготовленное окружение и lock (опционально сам spec)         |

Все команды уважают переменные окружения `COMFY_HOME`, `MODELS_DIR`, `COMFY_CACHE_ROOT` и `COMFY_OFFLINE`. Дополнительные аргументы позволяют переопределять пути или запускать в оффлайне.

### Документация

-   `manual.md` — быстрый старт и сценарии использования CLI.
-   `instructions.md` — подробные инструкции по созданию/проверке/запуску версий.
-   `tech.md` — архитектура кешей и структура каталогов.
-   `runpod.md` — рекомендации для RunPod (Pods и serverless).
-   `smoketest.md` — минимальный чек-лист проверки окружения.
-   `qa.md` — ответы на типовые вопросы.

### Требования

-   Python 3.11+
-   Git и доступ к интернету для первичного скачивания репозиториев и моделей
-   При желании — токены для Hugging Face (`HF_TOKEN`) и Civitai (`CIVITAI_TOKEN`)

### Статус

Schema v2 и новый CLI считаются основным путём использования. Старые lock-файлы и скрипты удалены.

### Лицензия

Будет добавлена позже.
