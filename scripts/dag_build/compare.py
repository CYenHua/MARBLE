"""
Compare coordination conditions on the same tasks from their traces.

    python scripts/dag_build/compare.py chain=result/traces/chain dag1=result/traces/dag1_pilot dag2=result/traces/dag2_pilot
    python scripts/dag_build/compare.py chain=result/traces/chain dag1=result/traces/dag1_pilot --tasks 3,4,7

Each argument is <label>=<trace dir> holding task_N.jsonl files; only tasks present in every
condition are compared. Per task it reports the judge's final scores (from the
evaluate_task_research call, so it works for modes that do not save them), the number of
acts, and the LLM calls / tokens / minutes spent. 'work' columns leave out the judge's
calls, which measure the run rather than being part of it.
"""

import argparse
import glob
import json
import os
import re
from typing import Any, Dict, List, Optional

DIMENSIONS = ["innovation", "safety", "feasibility"]


def scores(events: List[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    for e in reversed(events):
        if e["step"] == "evaluate_task_research":
            found = {d: re.search(rf'"{d}"\s*:\s*(\d+(?:\.\d+)?)', e["response"] or "") for d in DIMENSIONS}
            if all(found.values()):
                return {d: float(m.group(1)) for d, m in found.items()}
    return None


def summarize(path: str) -> Dict[str, Any]:
    with open(path) as f:
        events = [json.loads(line) for line in f if line.strip()]
    work = [e for e in events if e["caller"] != "judge"]
    start = min(e["time"] - e["latency"] for e in events)
    return {
        "scores": scores(events),
        "acts": sum(e["step"] == "act" for e in events),
        "calls": len(work),
        "in_tok": sum(e["prompt_tokens"] or 0 for e in work),
        "out_tok": sum(e["completion_tokens"] or 0 for e in work),
        "minutes": (max(e["time"] for e in events) - start) / 60,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("conditions", nargs="+", help="label=trace_dir")
    parser.add_argument("--tasks", help="only these task ids, e.g. 3,4,7")
    args = parser.parse_args()

    dirs = dict(c.split("=", 1) for c in args.conditions)
    found = {
        label: {int(re.findall(r"\d+", os.path.basename(p))[0]): p for p in glob.glob(f"{d}/task_*.jsonl")}
        for label, d in dirs.items()
    }
    tasks = sorted(set.intersection(*(set(f) for f in found.values())))
    if args.tasks:
        tasks = [t for t in tasks if t in {int(x) for x in args.tasks.split(",")}]
    if not tasks:
        raise SystemExit("no task has a trace in every condition")
    data = {label: {t: summarize(found[label][t]) for t in tasks} for label in dirs}

    width = max(len(label) for label in dirs)
    header = f"{'task':>4}  {'cond':<{width}} {'innov':>5} {'safe':>5} {'feas':>5} {'mean':>5} {'acts':>5} {'work calls':>10} {'in_tok':>8} {'out_tok':>8} {'min':>6}"
    print(header)
    for t in tasks:
        for label in dirs:
            r = data[label][t]
            s = r["scores"]
            cells = [f"{s[d]:>5.0f}" for d in DIMENSIONS] + [f"{sum(s.values()) / 3:>5.2f}"] if s else [f"{'-':>5}"] * 4
            print(
                f"{t:>4}  {label:<{width}} {' '.join(cells)} {r['acts']:>5} {r['calls']:>10} "
                f"{r['in_tok']:>8} {r['out_tok']:>8} {r['minutes']:>6.1f}"
            )
        print()

    print(f"mean over {len(tasks)} tasks {tasks}")
    print(header.replace("task", "    ", 1))
    for label in dirs:
        rows = list(data[label].values())
        scored = [r["scores"] for r in rows if r["scores"]]
        cells = [f"{sum(s[d] for s in scored) / len(scored):>5.2f}" for d in DIMENSIONS] if scored else [f"{'-':>5}"] * 3
        overall = f"{sum(sum(s.values()) / 3 for s in scored) / len(scored):>5.2f}" if scored else f"{'-':>5}"
        n = len(rows)
        print(
            f"{'':>4}  {label:<{width}} {' '.join(cells)} {overall} {sum(r['acts'] for r in rows) / n:>5.1f} "
            f"{sum(r['calls'] for r in rows) / n:>10.1f} {sum(r['in_tok'] for r in rows) / n:>8.0f} "
            f"{sum(r['out_tok'] for r in rows) / n:>8.0f} {sum(r['minutes'] for r in rows) / n:>6.1f}"
        )
        if len(scored) < n:
            print(f"{'':>6}({n - len(scored)} task(s) without a parsable final score)")


if __name__ == "__main__":
    main()
