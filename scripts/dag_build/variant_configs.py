"""
Copy a directory of configs with a few settings changed, so a variant keeps exactly the
same agents, roles and edges as the original and differs only in what is overridden.

    python scripts/dag_build/variant_configs.py configs/dag_eval configs/dag_note_eval --handoff note --summarize all
    python scripts/dag_build/variant_configs.py configs/dag_eval configs/dag_note_norole_eval --handoff note --summarize all --no-sub-task
    python scripts/dag_build/variant_configs.py configs/dag_eval configs/dag2_eval --max-iterations 2

Outputs go to result/<name of the new directory>/task_N.jsonl.
"""

import argparse
import glob
import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(__file__))
from make_configs import write_yaml  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", help="directory with task_N.yaml configs")
    parser.add_argument("target", help="directory for the variant configs")
    parser.add_argument("--max-iterations", type=int)
    parser.add_argument("--handoff", choices=["full", "note"], help="DAG mode: what non-root nodes receive")
    parser.add_argument("--summarize", choices=["sinks", "all"], help="DAG mode: whose outputs the planner summarizes")
    parser.add_argument(
        "--no-sub-task", action="store_true", help="DAG mode: leave the role's dag_task out of node prompts"
    )
    args = parser.parse_args()

    result_dir = f"result/{os.path.basename(os.path.normpath(args.target))}"
    for path in sorted(glob.glob(f"{args.source}/task_*.yaml")):
        with open(path) as f:
            config = yaml.safe_load(f)
        name = os.path.basename(path)
        config["output"]["file_path"] = f"{result_dir}/{name.replace('.yaml', '.jsonl')}"
        if args.max_iterations is not None:
            config["environment"]["max_iterations"] = args.max_iterations
        dag = config.setdefault("dag", {})
        if args.handoff:
            dag["handoff"] = args.handoff
        if args.summarize:
            dag["summarize"] = args.summarize
        if args.no_sub_task:
            dag["sub_task"] = False
        if not dag:
            del config["dag"]
        write_yaml(config, f"{args.target}/{name}")
        print(f"{args.target}/{name} -> {config['output']['file_path']}  dag={config.get('dag', {})}")


if __name__ == "__main__":
    main()
