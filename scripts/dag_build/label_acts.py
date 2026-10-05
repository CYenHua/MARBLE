"""
Tag every chain `act` in the traces with a role from roles.yaml, using an LLM.

    python scripts/dag_build/label_acts.py result/traces/chain/*.jsonl
    python scripts/dag_build/label_acts.py result/traces/chain_001.jsonl --model gemma-4-31b-it

Labels are appended to --out (one JSON line per act) and reused on reruns, so only new
acts are sent to the model. Inspect them with --show, then run build_dag.py.
"""

import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
os.environ.pop("MARBLE_TRACE", None)  # do not trace the labelling calls themselves

from trace_view import load_runs  # noqa: E402

from marble.llms.model_prompting import model_prompting  # noqa: E402

PROMPT = """You are analysing a multi-agent research collaboration. Several researcher agents take
turns; each turn one agent receives a sub-task and writes an output. Classify what this turn
mainly did, using exactly one of these roles:

{roles}

[Sub-task given to the agent]
{subtask}

[Agent output]
{output}

Answer with JSON only: {{"role": "<one role name>", "reason": "<one short sentence>"}}"""


def extract_acts(name: str, run: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    One entry per `act` call, with the sub-task it was given: the original task for
    the first act, afterwards the planning_task chosen in the previous plan_next_agent.
    """
    acts: List[Dict[str, Any]] = []
    subtask = "(the original task: generate a research idea from the given Introduction)"
    for e in run:
        if e["step"] == "plan_next_agent":
            match = re.search(r'"planning_task"\s*:\s*"((?:[^"\\]|\\.)*)"', e["response"] or "")
            if match:
                try:
                    subtask = json.loads(f'"{match.group(1)}"')
                except json.JSONDecodeError:
                    subtask = match.group(1)
        elif e["step"] == "act":
            output = e["response"] or ""
            if e["tool_calls"]:
                output += "\n[tool calls] " + ", ".join(
                    f"{tc['name']}({tc['arguments']})" for tc in e["tool_calls"]
                )
            acts.append({"trace": name, "seq": e["seq"], "agent": e["caller"], "subtask": subtask, "output": output})
    for pos, act in enumerate(acts):
        act["pos"], act["n_acts"] = pos, len(acts)
    return acts


def classify(act: Dict[str, Any], roles: List[Dict[str, str]], model: str, max_chars: int) -> Dict[str, Any]:
    names = [r["name"] for r in roles]
    prompt = PROMPT.format(
        roles="\n".join(f"- {r['name']}: {r['description']}" for r in roles),
        subtask=act["subtask"][:max_chars],
        output=act["output"][:max_chars],
    )
    reply = model_prompting(model, [{"role": "user", "content": prompt}], max_token_num=200)[0].content or ""
    match = re.search(r'"role"\s*:\s*"([^"]+)"', reply)
    role = match.group(1).strip() if match else ""
    reason = re.search(r'"reason"\s*:\s*"((?:[^"\\]|\\.)*)"', reply)
    label = {k: act[k] for k in ("trace", "seq", "pos", "n_acts", "agent")}
    label["subtask"] = act["subtask"][:300]
    label["role"] = role if role in names else "other"
    label["reason"] = reason.group(1) if reason else reply[:200]
    return label


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="+", help="chain trace .jsonl files")
    parser.add_argument("--roles", default=os.path.join(os.path.dirname(__file__), "roles.yaml"))
    parser.add_argument("--model", default="gemma-4-31b-it")
    parser.add_argument("--out", default="result/dag_build/act_labels.jsonl")
    parser.add_argument("--max-chars", type=int, default=6000, help="chars of sub-task / output sent to the model")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--show", action="store_true", help="print the labels after labelling")
    args = parser.parse_args()

    with open(args.roles) as f:
        roles = yaml.safe_load(f)["roles"]
    done = set()
    if os.path.exists(args.out):
        with open(args.out) as f:
            done = {(d["trace"], d["seq"]) for d in map(json.loads, f)}

    acts = [a for name, run in load_runs(args.paths) for a in extract_acts(name, run)]
    todo = [a for a in acts if (a["trace"], a["seq"]) not in done]
    print(f"{len(acts)} acts, {len(todo)} to label")
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with ThreadPoolExecutor(args.workers) as pool, open(args.out, "a") as out:
        for label in pool.map(lambda a: classify(a, roles, args.model, args.max_chars), todo):
            out.write(json.dumps(label, ensure_ascii=False) + "\n")
            out.flush()

    if args.show:
        wanted = {(a["trace"], a["seq"]) for a in acts}
        with open(args.out) as f:
            labels = [d for d in map(json.loads, f) if (d["trace"], d["seq"]) in wanted]
        for d in sorted(labels, key=lambda d: (d["trace"], d["seq"])):
            print(f"{d['trace']}  #{d['seq']:<3} {d['agent']:<8} {d['role']:<18} {d['reason']}")


if __name__ == "__main__":
    main()
