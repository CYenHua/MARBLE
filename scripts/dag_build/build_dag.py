"""
Turn the act labels from label_acts.py into a role-level DAG template.

    python scripts/dag_build/build_dag.py
    python scripts/dag_build/build_dag.py --min-edge 3 --min-role 2 --out result/dag_build/dag_template.yaml

1. Per run, the acts in order give a role sequence, e.g. ideation -> method_design -> critique.
2. Count role -> role transitions over all runs (self-loops counted but not used as edges).
3. Order roles by their mean relative position in the runs (0 = first act, 1 = last act).
   The final role (--final-role, default writing) is left out of this ordering: agents
   sometimes draft the 5q answer early, but in the DAG it always comes last.
4. Keep a transition as an edge if it goes forward in that order and occurs >= --min-edge
   times; backward transitions (loops) are dropped so the result is acyclic.
5. A role other than the first that has no kept incoming edge is not supported by the
   data and is dropped (repeated until stable, since dropping a role can orphan another).
6. Every remaining role without a successor gets an edge to the final role, so the DAG
   has a single sink.

The template lists roles (with their dag_task from roles.yaml) and edges; edit it by hand
if needed, then run assign_roles.py, which runs the roles in a topological order.
"""

import argparse
import json
import os
from collections import Counter, defaultdict
from typing import Dict, List

import yaml


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--labels", default="result/dag_build/act_labels.jsonl")
    parser.add_argument("--roles", default=os.path.join(os.path.dirname(__file__), "roles.yaml"))
    parser.add_argument("--out", default="result/dag_build/dag_template.yaml")
    parser.add_argument("--min-role", type=int, default=2, help="drop roles seen in fewer runs than this")
    parser.add_argument("--min-edge", type=int, default=2, help="drop transitions seen fewer times than this")
    parser.add_argument("--final-role", default="writing", help="role placed last as the single sink ('' for none)")
    args = parser.parse_args()

    with open(args.roles) as f:
        catalogue = {r["name"]: r for r in yaml.safe_load(f)["roles"]}
    runs: Dict[str, List[dict]] = defaultdict(list)
    with open(args.labels) as f:
        for d in map(json.loads, f):
            runs[d["trace"]].append(d)
    sequences = {t: [d["role"] for d in sorted(acts, key=lambda d: d["seq"])] for t, acts in runs.items()}

    transitions: Counter = Counter()
    positions: Dict[str, List[float]] = defaultdict(list)
    runs_with: Counter = Counter()
    for seq in sequences.values():
        for i, role in enumerate(seq):
            positions[role].append(i / max(len(seq) - 1, 1))
        runs_with.update(set(seq))
        transitions.update(zip(["START"] + seq, seq + ["END"]))

    print(f"{len(sequences)} runs\n")
    for trace, seq in sorted(sequences.items()):
        print(f"{trace}\n    {' -> '.join(seq)}")

    mean_pos = {r: sum(p) / len(p) for r, p in positions.items()}
    print(f"\n{'role':<18} {'acts':>5} {'runs':>5} {'mean pos':>9}")
    for role in sorted(mean_pos, key=mean_pos.get):
        print(f"{role:<18} {len(positions[role]):>5} {runs_with[role]:>5} {mean_pos[role]:>9.2f}")

    print("\ntransitions (A -> B: count):")
    for (a, b), n in transitions.most_common():
        print(f"  {a:>18} -> {b:<18} {n}")

    final = args.final_role
    candidates = [
        r for r in sorted(mean_pos, key=mean_pos.get) if runs_with[r] >= args.min_role and r in catalogue and r != final
    ]
    while True:
        rank = {r: i for i, r in enumerate(candidates)}
        edges = [
            [a, b]
            for (a, b), n in transitions.most_common()
            if a in rank and b in rank and rank[a] < rank[b] and n >= args.min_edge
        ]
        unsupported = [r for r in candidates[1:] if not any(b == r for _, b in edges)]
        if not unsupported:
            break
        candidates = [r for r in candidates if r not in unsupported]
    roles = list(candidates)
    if final:
        sinks = [r for r in roles if not any(a == r for a, _ in edges)]
        edges += [[r, final] for r in sinks]
        roles.append(final)
    rank = {r: i for i, r in enumerate(roles)}
    edges.sort(key=lambda e: (rank[e[0]], rank[e[1]]))

    template = {
        "roles": [{"name": r, "dag_task": catalogue[r]["dag_task"]} for r in roles],
        "edges": edges,
        "source": {
            "labels": args.labels,
            "runs": len(sequences),
            "edge_counts": {f"{a} -> {b}": transitions[(a, b)] for a, b in edges},
        },
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        yaml.dump(template, f, allow_unicode=True, sort_keys=False, width=110)
    print(f"\nDAG ({len(roles)} roles):")
    for a, b in edges:
        print(f"  {a} -> {b}")
    dropped = sorted(set(mean_pos) - set(roles))
    if dropped:
        print(f"dropped roles (rare, without a supported incoming edge, or 'other'): {dropped}")
    print(f"written to {args.out}")


if __name__ == "__main__":
    main()
