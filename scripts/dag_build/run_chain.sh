#!/bin/bash
# Run every chain config with tracing on, a few in parallel.
#   bash scripts/dag_build/run_chain.sh [config_dir] [parallel]
# Trace of configs/chain/task_3.yaml -> result/traces/chain/task_3.jsonl, log -> logs/chain/task_3.log
# Configs whose trace already exists are skipped; delete the trace to rerun.

CONFIG_DIR="${1:-configs/chain}"
PARALLEL="${2:-4}"
PYTHON="${PYTHON:-.venv/bin/python}"
TRACE_DIR="result/traces/$(basename "$CONFIG_DIR")"
LOG_DIR="logs/$(basename "$CONFIG_DIR")"
mkdir -p "$TRACE_DIR" "$LOG_DIR"

run_one() {
    config="$1"
    name="$(basename "$config" .yaml)"
    if [ -s "$TRACE_DIR/$name.jsonl" ]; then
        echo "skip $name (trace exists)"
        return
    fi
    echo "start $name"
    rm -f "$TRACE_DIR/$name.jsonl.part"
    MARBLE_TRACE="$TRACE_DIR/$name.jsonl.part" "$PYTHON" marble/main.py --config_path "$config" \
        > "$LOG_DIR/$name.log" 2>&1
    status=$?
    # Only a finished run counts; a failed one keeps its .part trace for debugging
    [ $status -eq 0 ] && mv "$TRACE_DIR/$name.jsonl.part" "$TRACE_DIR/$name.jsonl"
    echo "done  $name (exit $status)"
}
export -f run_one
export TRACE_DIR LOG_DIR PYTHON

ls "$CONFIG_DIR"/*.yaml | sort -V | xargs -P "$PARALLEL" -I{} bash -c 'run_one {}'
