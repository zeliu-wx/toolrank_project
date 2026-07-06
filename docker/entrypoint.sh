#!/usr/bin/env bash
set -euo pipefail

# Docker-in-Docker: start the daemon inside the image when needed.
# SmartBugs uses this internal daemon so temporary tool paths stay visible in the
# same filesystem namespace.
if ! docker info >/dev/null 2>&1; then
  dockerd --iptables=false --bridge=none --ip-forward=false --ip-masq=false >/var/log/dockerd.log 2>&1 &
  for _ in $(seq 1 60); do
    docker info >/dev/null 2>&1 && break
    sleep 1
  done
  if ! docker info >/dev/null 2>&1; then
    echo "[error] internal dockerd did not start; execution requires docker run --privileged." >&2
    echo "[error] recommendation-only flows can continue; dockerd log tail follows:" >&2
    tail -n 30 /var/log/dockerd.log >&2 2>/dev/null || true
  fi
fi

exec lakes "$@"
