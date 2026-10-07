"""
How many of a task's agents actually act in a run, and in what order.

    python scripts/dag_build/coverage.py result/traces/chain result/traces/chain_eval
    python scripts/dag_build/coverage.py result/traces/chain_big

For every task_N.jsonl in the given trace directories: team size, number of acts, distinct
agents that acted, coverage (distinct / team size) and the act order (agent numbers).
"""

import argparse
import glob
import json
import re

BENCH = "multiagentbench/research/research_main.jsonl"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dirs", nargs="+", help="trace directories with task_N.jsonl files")
    parser.add_argument("--bench", default=BENCH)
    args = parser.parse_args()

    team = {}
    with open(args.bench) as f:
        for line in f:
            if line.strip():
                data = json.loads(line)
                team[data["task_id"]] = len(data["agents"])

    print(f"{'trace':<42} {'n':>3} {'acts':>4} {'used':>4} {'cov':>5}  act order")
    for d in args.dirs:
        paths = sorted(glob.glob(f"{d}/task_*.jsonl"), key=lambda p: int(re.findall(r"task_(\d+)", p)[-1]))
        for path in paths:
            task_id = int(re.findall(r"task_(\d+)", path)[-1])
            with open(path) as f:
                acts = [e["caller"] for e in map(json.loads, f) if e["step"] == "act"]
            used = len(set(acts))
            order = " ".join(a.replace("agent", "") for a in acts)
            print(f"{path:<42} {team[task_id]:>3} {len(acts):>4} {used:>4} {used / team[task_id]:>5.0%}  {order}")


if __name__ == "__main__":
    main()
