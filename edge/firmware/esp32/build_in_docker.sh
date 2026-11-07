#!/usr/bin/env bash
# Compile the firmware in a container. PlatformIO caches its toolchain in PIO_CACHE. Nothing gets flashed.
# Uses the example Wi-Fi header when no real one exists, so this works from a clean checkout.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PIO_CACHE="${PIO_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/st2fb-platformio}"
mkdir -p "$PIO_CACHE"
IMAGE=python:3.12-slim@sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54
exec docker run --rm --user "$(id -u):$(id -g)" \
  -e HOME=/tmp/home -e PLATFORMIO_CORE_DIR=/pio -e PIP_DISABLE_PIP_VERSION_CHECK=1 \
  -v "$PIO_CACHE:/pio" -v "$HERE:/src:ro" --tmpfs /tmp/home:uid="$(id -u)",gid="$(id -g)" \
  --tmpfs /work:uid="$(id -u)",gid="$(id -g)",size=2g \
  "$IMAGE" sh -c '
    set -e
    pip install --quiet --no-cache-dir --target /tmp/home/pio platformio==6.1.16
    cp -r /src/. /work/ && cd /work && rm -rf .pio
    [ -f include/wifi_secrets.h ] || cp include/wifi_secrets.h.example include/wifi_secrets.h
    PYTHONPATH=/tmp/home/pio python3 -m platformio run -e esp32dev
    PYTHONPATH=/tmp/home/pio python3 -m platformio run -e esp32dev -t size | tail -n 8
  '
