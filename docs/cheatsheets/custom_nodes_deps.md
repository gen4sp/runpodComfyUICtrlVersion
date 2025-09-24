# Установка кастом нод и зависимостей

## Пиновка зависимостей из requirements.txt

```bash
python3 scripts/pin_requirements.py --requirements ./requirements.txt --lock lockfiles/comfy-my-version.lock.json --in-place --pretty
```

## Пиновка с явными URL для Torch (GPU CUDA 12.4)

```bash
python3 scripts/pin_requirements.py \
  --requirements ./requirements.txt \
  --wheel-url torch=https://download.pytorch.org/whl/cu124/torch-2.3.0%2Bcu124-cp311-cp311-linux_x86_64.whl \
  --wheel-url torchvision=https://download.pytorch.org/whl/cu124/torchvision-0.18.0%2Bcu124-cp311-cp311-linux_x86_64.whl \
  --wheel-url xformers=https://download.pytorch.org/whl/cu124/xformers-0.0.26-cp311-cp311-linux_x86_64.whl \
  --lock lockfiles/comfy-my-version.lock.json --in-place --pretty
```

## Пиновка для CPU

```bash
python3 scripts/pin_requirements.py \
  --requirements ./requirements.txt \
  --wheel-url torch=https://download.pytorch.org/whl/cpu/torch-2.3.0%2Bcpu-cp311-cp311-manylinux2014_x86_64.whl \
  --wheel-url torchvision=https://download.pytorch.org/whl/cpu/torchvision-0.18.0%2Bcpu-cp311-cp311-manylinux2014_x86_64.whl \
  --lock lockfiles/comfy-my-version.lock.json --in-place --pretty
```

## Оффлайн пиновка с локальными wheels

```bash
python3 scripts/pin_requirements.py \
  --requirements ./requirements.txt \
  --offline --wheels-dir /path/to/wheels \
  --lock lockfiles/comfy-my-version.lock.json --in-place
```

## Параметры pin_requirements.py

-   `--requirements FILE` — файл с зависимостями (обязательно)
-   `--lock FILE` — выходной lock-файл
-   `--in-place` — обновить существующий lock-файл
-   `--pretty` — человекочитаемый JSON
-   `--offline` — оффлайн режим (только локальные wheels)
-   `--wheels-dir DIR` — директория с wheel-артефактами
-   `--wheel-url name=url` — подмена URL для пакета (можно повторять)

## Установка кастом нод вручную

### Из GitHub (автоматическая установка)

```bash
cd "$COMFY_HOME"
source .venv/bin/activate
git clone https://github.com/city96/ComfyUI-GGUF custom_nodes/ComfyUI-GGUF
cd custom_nodes/ComfyUI-GGUF
pip install -r requirements.txt
```

### Из Hugging Face

```bash
cd "$COMFY_HOME"
source .venv/bin/activate
git clone https://huggingface.co/spaces/city96/ComfyUI-GGUF custom_nodes/ComfyUI-GGUF
cd custom_nodes/ComfyUI-GGUF
pip install -r requirements.txt
```

## Проверка установки кастом нод

```bash
cd "$COMFY_HOME"
source .venv/bin/activate
python -c "import custom_nodes.ComfyUI-GGUF; print('GGUF node loaded')"
```

## Обновление кастом нод

```bash
cd "$COMFY_HOME/custom_nodes/ComfyUI-GGUF"
git pull
cd "$COMFY_HOME"
source .venv/bin/activate
pip install -r custom_nodes/ComfyUI-GGUF/requirements.txt --upgrade
```

## Удаление кастом нод

```bash
cd "$COMFY_HOME"
rm -rf custom_nodes/ComfyUI-GGUF
```

## Создание версии с кастом нодами

```bash
python3 scripts/create_version.py \
  --name "with-gguf" \
  --custom-node repo=https://github.com/city96/ComfyUI-GGUF,name=gguf \
  --custom-node repo=https://github.com/kijai/ComfyUI-WanVideoWrapper,name=wan-wrapper \
  --requirements ./requirements.txt \
  --pretty
```

## Популярные кастом ноды

### Для FLUX

-   `https://github.com/city96/ComfyUI-GGUF` — GGUF загрузчик
-   `https://github.com/kijai/ComfyUI-FluxTrainer` — Flux trainer
-   `https://github.com/XLabs-AI/x-flux-comfyui` — X-Flux

### Для Wan

-   `https://github.com/kijai/ComfyUI-WanVideoWrapper` — Wan Video wrapper
-   `https://github.com/city96/ComfyUI-GGUF` — GGUF загрузчик

### Для Stable Diffusion

-   `https://github.com/comfyanonymous/ComfyUI_experiments` — экспериментальные ноды
-   `https://github.com/ltdrdata/ComfyUI-Manager` — менеджер нод

### Для видео

-   `https://github.com/kijai/ComfyUI-VideoHelperSuite` — видео хелперы
-   `https://github.com/Fannovel16/comfyui_controlnet_aux` — ControlNet aux

## Проверка зависимостей в venv

```bash
cd "$COMFY_HOME"
source .venv/bin/activate
pip list | grep torch
pip list | grep torchvision
```

## Создание нового requirements.txt из venv

```bash
cd "$COMFY_HOME"
source .venv/bin/activate
pip freeze > requirements-new.txt
```
