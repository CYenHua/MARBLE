"""
Build per-task DAG configs from a role-level DAG template: an LLM reads the task's agent
profiles and assigns one agent to each role.

    python scripts/dag_build/assign_roles.py --tasks 1-10
    python scripts/dag_build/assign_roles.py --tasks 11-20 --template result/dag_build/dag_template.yaml

Each role becomes one DAG node: the assigned agent with the role's dag_task, and every
template edge becomes a 'feeds' relationship. Agents without a role are left out. If a task
has fewer agents than roles, an agent may take several roles; its extra nodes get the id
'<agent>_<role>' with the same profile. Assignments and the model's reasons are appended
to result/dag_build/assignments.jsonl.
"""

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))
os.environ.pop("MARBLE_TRACE", None)

from make_configs import BENCH, build_config, load_tasks, parse_ids, write_yaml  # noqa: E402

from marble.llms.model_prompting import model_prompting  # noqa: E402

PROMPT = """A team of researchers will collaborate on the task below through a fixed workflow.
Each workflow role must be carried out by one researcher. Assign researchers to roles so that
each role goes to the researcher whose background fits it and the research topic best.
{reuse_rule}

[Task]
{task}

[Workflow roles, in execution order]
{roles}

[Researchers]
{agents}

Answer with JSON only:
{{"assignments": {{"<role name>": "<agent_id>", ...}}, "reasons": {{"<role name>": "<one short sentence>", ...}}}}"""


def ask(
    task: Dict[str, Any], roles: List[Dict[str, str]], model: str, profile_chars: int, task_chars: int
) -> tuple:
    agents = task["agents"]
    reuse = len(agents) < len(roles)
    prompt = PROMPT.format(
        reuse_rule=(
            "There are fewer researchers than roles, so some researchers must take more than one role."
            if reuse
            else "Every role must go to a different researcher; some researchers may get no role."
        ),
        task=task["task"]["content"].strip()[:task_chars],
        roles="\n".join(f"- {r['name']}: {r['dag_task']}" for r in roles),
        agents="\n\n".join(f"{a['agent_id']}: {a['profile'].strip()[:profile_chars]}" for a in agents),
    )
    reply = model_prompting(model, [{"role": "user", "content": prompt}], max_token_num=1024)[0].content or ""
    return reply, reuse


def parse(reply: str, roles: List[Dict[str, str]], agent_ids: List[str], reuse: bool) -> Optional[Dict[str, Any]]:
    """
    Return {'assignments': ..., 'reasons': ...} if the reply is a valid assignment, else None.
    The model sometimes corrects itself within one reply, so the last valid JSON object wins.
    """
    decoder = json.JSONDecoder()
    for start in reversed([m.start() for m in re.finditer(r"\{", reply)]):
        try:
            data, _ = decoder.raw_decode(reply, start)
        except json.JSONDecodeError:
            continue
        result = _validate(data, roles, agent_ids, reuse)
        if result:
            return result
    return None


def _validate(data: Any, roles: List[Dict[str, str]], agent_ids: List[str], reuse: bool) -> Optional[Dict[str, Any]]:
    if not isinstance(data, dict) or not isinstance(data.get("assignments"), dict):
        return None
    assignments = data["assignments"]
    names = [r["name"] for r in roles]
    if set(assignments) != set(names) or any(assignments[n] not in agent_ids for n in names):
        return None
    if not reuse and len(set(assignments.values())) != len(names):
        return None
    return {"assignments": {n: assignments[n] for n in names}, "reasons": data.get("reasons") or {}}


def dag_config(
    base: Dict[str, Any], task: Dict[str, Any], roles: List[Dict[str, str]], edges: List[List[str]], assignments: Dict[str, str]
) -> Dict[str, Any]:
    profiles = {a["agent_id"]: a for a in base["agents"]}
    node_of: Dict[str, str] = {}
    agents = []
    for role in roles:
        agent_id = assignments[role["name"]]
        node = agent_id if agent_id not in node_of.values() else f"{agent_id}_{role['name']}"
        node_of[role["name"]] = node
        agents.append({**profiles[agent_id], "agent_id": node, "role": role["name"], "dag_task": role["dag_task"]})
    base["agents"] = agents
    base["relationships"] = [[node_of[a], node_of[b], "feeds"] for a, b in edges]
    return base


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tasks", default="1-10")
    parser.add_argument("--template", default="result/dag_build/dag_template.yaml", help="output of build_dag.py")
    parser.add_argument("--bench", default=BENCH)
    parser.add_argument("--base", default="test_dag.yaml", help="config to copy model / limits / metrics from")
    parser.add_argument("--out", default="configs/dag")
    parser.add_argument("--result-dir", default="result/dag")
    parser.add_argument("--max-iterations", type=int, default=1, help="rounds over the whole DAG")
    parser.add_argument("--model", default="gemma-4-31b-it")
    parser.add_argument("--log", default="result/dag_build/assignments.jsonl")
    parser.add_argument("--profile-chars", type=int, default=1500)
    parser.add_argument("--task-chars", type=int, default=3000)
    parser.add_argument("--retries", type=int, default=3)
    args = parser.parse_args()

    with open(args.template) as f:
        template = yaml.safe_load(f)
    with open(args.base) as f:
        base_config = yaml.safe_load(f)
    roles, edges = template["roles"], template["edges"]
    os.makedirs(os.path.dirname(args.log) or ".", exist_ok=True)
    tasks = load_tasks(args.bench, parse_ids(args.tasks))
    # Rerunning a task replaces its earlier assignment in the log
    if os.path.exists(args.log):
        with open(args.log) as f:
            kept = [line for line in f if json.loads(line)["task_id"] not in tasks]
        with open(args.log, "w") as f:
            f.writelines(kept)

    for task_id, task in sorted(tasks.items()):
        agent_ids = [a["agent_id"] for a in task["agents"]]
        result = None
        for _ in range(args.retries):
            reply, reuse = ask(task, roles, args.model, args.profile_chars, args.task_chars)
            result = parse(reply, roles, agent_ids, reuse)
            if result:
                break
        if result is None:
            print(f"task {task_id}: no valid assignment after {args.retries} tries, last reply:\n{reply}")
            continue

        config = build_config(
            base_config, task, "dag", f"{args.result_dir}/task_{task_id}.jsonl", args.max_iterations
        )
        config = dag_config(config, task, roles, edges, result["assignments"])
        path = f"{args.out}/task_{task_id}.yaml"
        write_yaml(config, path)
        with open(args.log, "a") as f:
            f.write(json.dumps({"task_id": task_id, "template": args.template, **result}, ensure_ascii=False) + "\n")
        print(f"task {task_id} ({len(agent_ids)} agents) -> {path}")
        for role in roles:
            name = role["name"]
            print(f"    {name:<18} {result['assignments'][name]:<8} {result['reasons'].get(name, '')}")


if __name__ == "__main__":
    main()
