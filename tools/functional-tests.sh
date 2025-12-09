#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TEST_PATH="${PROJECT_ROOT}/tests/tachyon_tests/functional"

args=("$@")
has_concurrency=0
for arg in "${args[@]}"; do
  case "$arg" in
    --concurrency|--concurrency=*|-c|-c*)
      has_concurrency=1
      ;;
  esac
done

if [[ $has_concurrency -eq 0 ]]; then
  procs="$(nproc --ignore 2 2>/dev/null || nproc)"
  [[ "$procs" =~ ^[0-9]+$ ]] || procs=1
  conc=$(( procs / 3 ))
  if (( conc < 1 )); then
    conc=1
  fi
  args+=("--concurrency" "$conc")
fi

# Tests within a YAML file are sequential and depend on each other.
# Each YAML file gets its own fresh app and database container.
cmd=(stestr --test-path="${TEST_PATH}" run "${args[@]}")

echo "Running: ${cmd[*]}"
"${cmd[@]}"

echo "Running: stestr slowest"
stestr slowest
