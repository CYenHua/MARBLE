"""
Generate per-task chain configs from a MultiAgentBench jsonl, using a local config as template.

    python scripts/dag_build/make_configs.py --tasks 1-10
    python scripts/dag_build/make_configs.py --tasks 1,3,5 --max-iterations 3 --out configs/chain

Everything except agents / relationships / task / output path comes from the template
(model, memory, metrics, output_limits ...), so local settings carry over.
"""

import argparse
import json
import os
from typing import Any, Dict, List

import yaml

BENCH = "multiagentbench/research/research_main.jsonl"


def parse_ids(spec: str) -> List[int]:
    """'1-3,7' -> [1, 2, 3, 7]"""
    ids: List[int] = []
    for part in spec.split(","):
        lo, _, hi = part.partition("-")
        ids.extend(range(int(lo), int(hi or lo) + 1))
    return ids


def load_tasks(path: str, ids: List[int]) -> Dict[int, Dict[str, Any]]:
    tasks = {}
    with open(path) as f:
        for line in f:
            if line.strip():
                data = json.loads(line)
                if data["task_id"] in ids:
                    tasks[data["task_id"]] = data
    missing = set(ids) - set(tasks)
    if missing:
        raise SystemExit(f"task ids not found in {path}: {sorted(missing)}")
    return tasks


def build_config(
    template: Dict[str, Any],
    task: Dict[str, Any],
    mode: str,
    output_path: str,
    max_iterations: int,
) -> Dict[str, Any]:
    config = json.loads(json.dumps(template))  # deep copy
    llm = config["llm"]
    config["agents"] = [
        {"agent_id": a["agent_id"], "profile": a["profile"], "type": a.get("type") or "BaseAgent", "llm": llm}
        for a in task["agents"]
    ]
    config["relationships"] = task["relationships"]
    config["task"] = task["task"]
    config["coordinate_mode"] = mode
    config["environment"]["max_iterations"] = max_iterations
    config["output"]["file_path"] = output_path
    config["task_id"] = task["task_id"]
    return config


def write_yaml(config: Dict[str, Any], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(config, f, allow_unicode=True, sort_keys=False, width=110)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tasks", default="1-10", help="task ids, e.g. 1-10 or 1,4,7")
    parser.add_argument("--bench", default=BENCH)
    parser.add_argument("--template", default="test_chain.yaml")
    parser.add_argument("--out", default="configs/chain")
    parser.add_argument("--result-dir", default="result/chain")
    parser.add_argument("--max-iterations", type=int, default=2, help="chain length = this x number of agents")
    args = parser.parse_args()

    with open(args.template) as f:
        template = yaml.safe_load(f)
    for task_id, task in sorted(load_tasks(args.bench, parse_ids(args.tasks)).items()):
        config = build_config(
            template, task, "chain", f"{args.result_dir}/task_{task_id}.jsonl", args.max_iterations
        )
        path = f"{args.out}/task_{task_id}.yaml"
        write_yaml(config, path)
        print(f"{path}: {len(task['agents'])} agents")


if __name__ == "__main__":
    main()
