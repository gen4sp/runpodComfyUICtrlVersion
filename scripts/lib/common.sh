#!/usr/bin/env bash

# Simple logging helpers
if [ -z "${_COMMON_SH_SOURCED-}" ]; then
  _COMMON_SH_SOURCED=1
  RED='\033[0;31m'
  GREEN='\033[0;32m'
  YELLOW='\033[1;33m'
  BLUE='\033[0;34m'
  NC='\033[0m'

  log_info() { printf "%b[INFO]%b %s\n" "$BLUE" "$NC" "$*"; }
  log_warn() { printf "%b[WARN]%b %s\n" "$YELLOW" "$NC" "$*"; }
  log_error() { printf "%b[ERROR]%b %s\n" "$RED" "$NC" "$*"; }
  log_ok() { printf "%b[OK]%b %s\n" "$GREEN" "$NC" "$*"; }
fi
