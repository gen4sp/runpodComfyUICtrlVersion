#!/usr/bin/env bash

# Strict mode for safer bash scripts
set -Eeuo pipefail
IFS=$'\n\t'

# Enable tracing when TRACE=1
if [ "${TRACE-0}" != "0" ]; then
  set -x
fi

# Basic error trap
trap 'echo "[ERROR] $BASH_SOURCE:$LINENO: $BASH_COMMAND" >&2' ERR
