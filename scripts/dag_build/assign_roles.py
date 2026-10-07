"""
Turn the role DAG template into per-task static configs: an LLM reads the task's agent
profiles and assigns one agent to each role, and the roles' topological order becomes the
task's fixed schedule.

    python scripts/dag_build/assign_roles.py --tasks 1-10
    python scripts/dag_build/assign_roles.py --tasks 12-21 --out configs/static_eval --result-dir result/static_eval
    python scripts/dag_build/assign_roles.py --tasks 12-21 --reuse-log   # rebuild configs, no LLM calls

A static config is the task's chain config (same template as make_configs.py) with
coordinate_mode: static and static.schedule, so it runs exactly like chain mode except that
the order of agents is fixed. If a task has fewer agents than roles, an agent takes several
roles and appears several times in the schedule. Assignments and the model's reasons go to
result/dag_build/assignments.jsonl; --reuse-log takes a task's assignment from there instead
of asking again (the model's choices are not reproducible).
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
    task: Dict[str, Any],
    roles: List[Dict[str, str]],
    model: str,
    profile_chars: int,
    task_chars: int,
    previous: Optional[str] = None,
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
    messages = [{"role": "user", "content": prompt}]
    if previous is not None:
        # Retry with the rejected answer in context, so the model fixes it instead of repeating it
        names = ", ".join(r["name"] for r in roles)
        rule = "" if reuse else " No agent_id may appear twice."
        messages += [
            {"role": "assistant", "content": previous},
            {
                "role": "user",
                "content": f"That answer is invalid. Assign exactly these roles: {names}, each to one of "
                f"{', '.join(a['agent_id'] for a in agents)}.{rule} Answer with the corrected JSON only.",
            },
        ]
    reply = model_prompting(model, messages, max_token_num=1024)[0].content or ""
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


def topological_order(roles: List[str], edges: List[List[str]]) -> List[str]:
    """Roles in an order that respects every edge; ties keep the template's order."""
    indegree = {r: sum(dst == r for _, dst in edges) for r in roles}
    ready = [r for r in roles if indegree[r] == 0]
    order: List[str] = []
    while ready:
        role = ready.pop(0)
        order.append(role)
        for src, dst in edges:
            if src == role:
                indegree[dst] -= 1
                if indegree[dst] == 0:
                    ready.append(dst)
        ready.sort(key=roles.index)
    if len(order) != len(roles):
        raise ValueError("the role DAG has a cycle")
    return order


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tasks", default="1-10")
    parser.add_argument(
        "--template",
        default=os.path.join(os.path.dirname(__file__), "dag_template.yaml"),
        help="role DAG from build_dag.py",
    )
    parser.add_argument("--bench", default=BENCH)
    parser.add_argument("--base", default="test_chain.yaml", help="chain config to copy settings from")
    parser.add_argument("--out", default="configs/static")
    parser.add_argument("--result-dir", default="result/static")
    parser.add_argument("--max-iterations", type=int, default=2, help="kept equal to the chain configs (unused)")
    parser.add_argument("--model", default="gemma-4-31b-it")
    parser.add_argument("--log", default="result/dag_build/assignments.jsonl")
    parser.add_argument("--reuse-log", action="store_true", help="use assignments already in --log")
    parser.add_argument("--profile-chars", type=int, default=1500)
    parser.add_argument("--task-chars", type=int, default=3000)
    parser.add_argument("--retries", type=int, default=3)
    args = parser.parse_args()

    with open(args.template) as f:
        template = yaml.safe_load(f)
    with open(args.base) as f:
        base_config = yaml.safe_load(f)
    roles = template["roles"]
    order = topological_order([r["name"] for r in roles], template["edges"])
    os.makedirs(os.path.dirname(args.log) or ".", exist_ok=True)
    tasks = load_tasks(args.bench, parse_ids(args.tasks))

    logged: Dict[int, Dict[str, Any]] = {}
    if os.path.exists(args.log):
        with open(args.log) as f:
            logged = {d["task_id"]: d for d in map(json.loads, f)}

    for task_id, task in sorted(tasks.items()):
        agent_ids = [a["agent_id"] for a in task["agents"]]
        if args.reuse_log and task_id in logged:
            result = {k: logged[task_id][k] for k in ("assignments", "reasons")}
        else:
            result, reply = None, None
            for _ in range(args.retries):
                reply, reuse = ask(task, roles, args.model, args.profile_chars, args.task_chars, reply)
                result = parse(reply, roles, agent_ids, reuse)
                if result:
                    break
            if result is None:
                print(f"task {task_id}: no valid assignment after {args.retries} tries, last reply:\n{reply}")
                continue
            # A new assignment replaces the task's earlier one in the log
            logged[task_id] = {"task_id": task_id, "template": args.template, **result}
            with open(args.log, "w") as f:
                for entry in logged.values():
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        config = build_config(
            base_config, task, "static", f"{args.result_dir}/task_{task_id}.jsonl", args.max_iterations
        )
        config["static"] = {"schedule": [result["assignments"][r] for r in order], "roles": order}
        path = f"{args.out}/task_{task_id}.yaml"
        write_yaml(config, path)
        print(f"task {task_id} ({len(agent_ids)} agents) -> {path}")
        for role in order:
            print(f"    {role:<18} {result['assignments'][role]:<8} {result['reasons'].get(role, '')}")


if __name__ == "__main__":
    main()
