## Smoketest: локальная ручная проверка

Набор шагов для проверки основных сценариев: создание версии, развёртывание окружения, запуск UI/handler и загрузка в GCS.

### Предусловия

-   Python 3.11+
-   Git
-   (Опционально) Docker для проверки образа
-   Созданное виртуальное окружение: `python -m venv .venv && source .venv/bin/activate`
-   Установленные зависимости: `pip install -r requirements.txt`

### 1. Подготовка путей

```bash
export COMFY_HOME="$(pwd)/smoke-comfy"
export MODELS_DIR="$(pwd)/smoke-models"
mkdir -p "$MODELS_DIR"
```

### 2. Создание спецификации

```bash
python3 scripts/version.py create smoke \
  --repo https://github.com/comfyanonymous/ComfyUI@master \
  --models '[{"source": "https://example.com/model.safetensors", "name": "dummy", "target_subdir": "checkpoints"}]' \
  --output versions/smoke.json
```

Проверьте, что файл `versions/smoke.json` создан и содержит `schema_version = 2`.

### 3. Проверка спецификации

```bash
python3 scripts/version.py validate smoke
```

Ожидаемое: вывод плана, создан файл кеша `~/.cache/runpod-comfy/resolved/smoke.lock.json`.

### 4. Развёртывание и запуск UI

```bash
python3 scripts/version.py realize smoke --target "$COMFY_HOME"
python3 scripts/version.py run-ui smoke --target "$COMFY_HOME" --port 9999 --extra-args -- --no-auto-launch &
UI_PID=$!
sleep 5
curl -sSf "http://127.0.0.1:9999" >/dev/null
kill "$UI_PID"
```

Ожидаемое: UI запускается без ошибок, HTTP-запрос возвращает код 200.

### 5. Запуск handler (base64)

```bash
echo '{"graph": {}}' > workflows/smoke.json
python3 scripts/version.py run-handler smoke \
  --workflow workflows/smoke.json \
  --output base64 --out-file smoke.b64
python3 - <<'PY'
import base64, json
with open('smoke.b64', 'rb') as fh:
    data = base64.b64decode(fh.read())
json.loads(data.decode('utf-8'))
PY
```

Ожидаемое: команда завершилась кодом 0, файл `smoke.b64` содержит JSON воркфлоу.

### 6. Запуск handler (GCS, опционально)

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/abs/path/sa.json
export GOOGLE_CLOUD_PROJECT=<project>
export GCS_BUCKET=<bucket>
export GCS_PREFIX=comfy/smoke
python3 scripts/version.py run-handler smoke \
  --workflow workflows/smoke.json \
  --output gcs --gcs-bucket "$GCS_BUCKET" --gcs-prefix "$GCS_PREFIX" --verbose
```

Ожидаемое: в stdout печатается `gs://` путь. Проверяйте логи на наличие signed URL (если настроено).

### 7. Очистка

```bash
python3 scripts/version.py delete smoke --target "$COMFY_HOME" --remove-spec
rm -f smoke.b64 workflows/smoke.json
```

### 8. Автотесты

```bash
pytest -q
```

Все тесты должны завершиться успешно.
