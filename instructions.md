## Руководство по использованию

Данный документ описывает, как пользоваться инструментами для управления версиями ComfyUI, локально и в Docker/RunPod.

### Предварительные требования

-   macOS, установленный Docker, Python 3.10+.
-   Доступ к интернету для скачивания зависимостей и моделей (или подготовленные wheel-артефакты и локальные источники).
-   (Опционально) Доступ к Google Cloud Storage для загрузки результатов.

### Переменные окружения

-   `COMFY_HOME` — базовая директория установки ComfyUI (локально или путь volume на RunPod).
-   `COMFY_VERSION_NAME` — удобное имя версии (используется для поиска lock-файла).
-   `GCS_BUCKET` — имя bucket для загрузки результатов (если используется вывод в GCS).
-   `GOOGLE_APPLICATION_CREDENTIALS` — путь к JSON ключу сервисного аккаунта.

### Инициализация ComfyUI

1. Запустите `scripts/init_comfyui.sh` с указанием `COMFY_HOME`.
2. Скрипт создаст `venv`, установит базовые зависимости и подготовит структуру.

Пример:

```bash
export COMFY_HOME="$HOME/comfy"
./scripts/init_comfyui.sh
```

### Создание lock-версии

Сгенерируйте lock-файл, зафиксировав SHA/версии:

```bash
python3 scripts/create_version.py --name "$COMFY_VERSION_NAME" \
  --comfy-repo https://github.com/comfyanonymous/ComfyUI \
  --custom-node repo=https://github.com/author/custom-node.git,name=custom-node \
  --requirements ./requirements.txt \
  --models-spec ./models/spec.yml
```

Результат: `lockfiles/comfy-$COMFY_VERSION_NAME.lock.json`.

### Верификация и скачивание моделей

```bash
python3 scripts/verify_models.py --lock lockfiles/comfy-$COMFY_VERSION_NAME.lock.json \
  --models-dir "$COMFY_HOME/models"
```

### Клонирование версии

Развернуть окружение по lock-файлу в новую директорию:

```bash
./scripts/clone_version.sh --lock lockfiles/comfy-$COMFY_VERSION_NAME.lock.json \
  --target "$HOME/comfy-$COMFY_VERSION_NAME"
```

### Удаление версии

```bash
./scripts/remove_version.sh --target "$HOME/comfy-$COMFY_VERSION_NAME"
```

### Сборка Docker-образа с handler

```bash
./scripts/build_docker.sh --version "$COMFY_VERSION_NAME"
```

### Локальный запуск handler

```bash
./scripts/run_handler_local.sh \
  --lock lockfiles/comfy-$COMFY_VERSION_NAME.lock.json \
  --workflow ./workflows/example.json \
  --output base64
```

Вместо `--output base64` можно опустить параметр и настроить GCS через переменные окружения.

### Выходные данные

-   `base64` — результат возвращается прямо в stdout/файл.
-   `gcs` — результат загружается в `gs://$GCS_BUCKET/...`, в ответе — ссылка/путь к объекту.

### Диагностика

-   Повторно запустите скрипты с флагом `--verbose` (если предусмотрен).
-   Проверьте корректность `GOOGLE_APPLICATION_CREDENTIALS` и прав на bucket.
-   Сравните текущие зависимости и SHA с содержимым lock-файла.
