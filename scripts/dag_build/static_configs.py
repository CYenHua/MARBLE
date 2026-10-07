"""
Make static-mode configs: the chain config of each task, unchanged except that the order of
agents is fixed in advance. The order is a topological order of the role DAG in the matching
DAG config (from assign_roles.py), with each role mapped to the agent assigned to it.

    python scripts/dag_build/static_configs.py --chain configs/chain_eval --dag configs/dag_eval --out configs/static_eval

Static mode runs the chain loop with this schedule: same prompts, agents, memory, planner and
evaluator calls as chain mode; only the next agent is given instead of chosen. Parallel roles
of the DAG (critique, experiment_design) run one after the other, each handing off to the next.
Outputs go to result/<name of --out>/task_N.jsonl.
"""

import argparse
import glob
import os
import sys
from typing import Any, Dict, List, Tuple

import yaml

sys.path.insert(0, os.path.dirname(__file__))
from make_configs import write_yaml  # noqa: E402


def schedule(dag_config: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """
    Topological order of the DAG nodes (ties broken by config order), as the agents to run
    and their roles. A node of an agent holding several roles is named '<agent>_<role>'.
    """
    nodes = [a["agent_id"] for a in dag_config["agents"]]
    role = {a["agent_id"]: a.get("role", "") for a in dag_config["agents"]}
    edges = [(src, dst) for src, dst, _ in dag_config["relationships"]]
    indegree = {n: sum(dst == n for _, dst in edges) for n in nodes}
    order: List[str] = []
    ready = [n for n in nodes if indegree[n] == 0]
    while ready:
        node = ready.pop(0)
        order.append(node)
        for src, dst in edges:
            if src == node:
                indegree[dst] -= 1
                if indegree[dst] == 0:
                    ready.append(dst)
        ready.sort(key=nodes.index)
    if len(order) != len(nodes):
        raise ValueError("the DAG has a cycle")
    agents = [n[: -len(role[n]) - 1] if role[n] and n.endswith(f"_{role[n]}") else n for n in order]
    return agents, [role[n] for n in order]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--chain", default="configs/chain_eval", help="chain configs (task_N.yaml)")
    parser.add_argument("--dag", default="configs/dag_eval", help="DAG configs with the role assignment")
    parser.add_argument("--out", default="configs/static_eval")
    args = parser.parse_args()

    result_dir = f"result/{os.path.basename(os.path.normpath(args.out))}"
    for dag_path in sorted(glob.glob(f"{args.dag}/task_*.yaml")):
        name = os.path.basename(dag_path)
        chain_path = f"{args.chain}/{name}"
        if not os.path.exists(chain_path):
            print(f"skip {name}: no chain config in {args.chain}")
            continue
        with open(dag_path) as f:
            agents, roles = schedule(yaml.safe_load(f))
        with open(chain_path) as f:
            config = yaml.safe_load(f)
        team = {a["agent_id"] for a in config["agents"]}
        if not set(agents) <= team:
            raise ValueError(f"{name}: scheduled agents {agents} are not all in the team {sorted(team)}")
        config["coordinate_mode"] = "static"
        config["static"] = {"schedule": agents, "roles": roles}
        config["output"]["file_path"] = f"{result_dir}/{name.replace('.yaml', '.jsonl')}"
        write_yaml(config, f"{args.out}/{name}")
        print(f"{args.out}/{name}: " + " -> ".join(f"{a}({r})" for a, r in zip(agents, roles)))


if __name__ == "__main__":
    main()
