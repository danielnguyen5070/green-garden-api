#!/bin/sh
# Container entrypoint: reset Prometheus multiprocess files, then run the command.
# Stale per-worker files from a previous run would otherwise be merged into /metrics.
set -eu

if [ -n "${PROMETHEUS_MULTIPROC_DIR:-}" ]; then
    mkdir -p "$PROMETHEUS_MULTIPROC_DIR"
    find "$PROMETHEUS_MULTIPROC_DIR" -mindepth 1 -delete
fi

exec "$@"
