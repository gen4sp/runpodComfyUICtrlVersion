#!/usr/bin/env bash
set -euo pipefail

export DOCKER_HOST="${DOCKER_HOST:-unix:///var/run/docker.sock}"
storage_driver="${DOCKER_STORAGE_DRIVER:-overlay2}"

dockerd --host="$DOCKER_HOST" \
        --data-root=/runpod-volume/.docker/data \
        --exec-root=/runpod-volume/.docker/exec \
        --storage-driver="$storage_driver" &
docker_pid=$!

until docker info >/dev/null 2>&1; do
  sleep 1
done

if [[ $# -eq 0 ]]; then
  set -- /start.sh
fi

exec /opt/nvidia/nvidia_entrypoint.sh "$@"