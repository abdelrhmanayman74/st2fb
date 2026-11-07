#!/usr/bin/env bash
# One command for everything that can run on this machine. All of it is simulated: no Raspberry Pi, no ESP32.
#   ./run_tests.sh          pipeline, conformance, integration, faults, short failover (about 5 minutes once built)
#   ./run_tests.sh --full   also the measurements behind docs/EDGE.md (about an hour): 30-repetition failover,
#                           jitter and real-time versus deterministic. Results land in results/.
#   ./run_tests.sh --keep   leave the stack running afterwards
set -euo pipefail
cd "$(dirname "$0")"
FULL=0; KEEP=0
for arg in "$@"; do
  case "$arg" in
    --full) FULL=1 ;;
    --keep) KEEP=1 ;;
    *) echo "unknown option: $arg"; exit 2 ;;
  esac
done

[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/pip install --quiet --disable-pip-version-check -r tests/requirements.txt
python3 scripts/bootstrap.py

cleanup() {
  docker rm -f st2fb-jitter-stress st2fb-replay-player >/dev/null 2>&1 || true
  docker compose down -v -t 1 --remove-orphans >/dev/null 2>&1 || true
}
if [ "$KEEP" = 0 ]; then trap cleanup EXIT; fi

export ALLOW_TEST_HOOKS=1
docker compose build --quiet
docker compose up -d --no-build
.venv/bin/python -m pytest tests -q --no-header
if [ "$FULL" = 1 ]; then
  .venv/bin/python tests/jitter_test.py --seconds 300
  docker compose up -d --no-build
  .venv/bin/python tests/failover_test.py --reps 30
  .venv/bin/python tests/realtime_vs_deterministic.py
fi
