"""
View LLM call traces written with MARBLE_TRACE=<file>.

    python scripts/trace_view.py result/trace.jsonl              # timeline + per-caller stats + hand-offs
    python scripts/trace_view.py result/trace.jsonl --show 7     # full prompt/response of call #7
    python scripts/trace_view.py result/traces/*.jsonl --flow    # hand-off counts summed over many runs
"""

import argparse
import json
from collections import Counter, defaultdict
from typing import Any, Dict, List, Tuple

Run = List[Dict[str, Any]]


def load_runs(paths: List[str]) -> List[Tuple[str, Run]]:
    """One run = the calls of one process in one file."""
    runs: List[Tuple[str, Run]] = []
    for path in paths:
        by_pid: Dict[int, Run] = defaultdict(list)
        with open(path) as f:
            for line in f:
                if line.strip():
                    event = json.loads(line)
                    by_pid[event["pid"]].append(event)
        for pid, events in by_pid.items():
            name = path if len(by_pid) == 1 else f"{path} (pid {pid})"
            runs.append((name, sorted(events, key=lambda e: e["seq"])))
    return runs


def one_line(text: Any, width: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= width else text[: width - 1] + "…"


def gist(event: Dict[str, Any]) -> str:
    if event["tool_calls"]:
        calls = []
        for tc in event["tool_calls"]:
            try:
                args = json.loads(tc["arguments"])
            except (TypeError, json.JSONDecodeError):
                args = {}
            target = args.get("target_agent_id")
            calls.append(f"{tc['name']}({target})" if target else tc["name"])
        return "→ " + ", ".join(calls)
    return one_line(event["response"], 70)


def print_timeline(run: Run) -> None:
    print(f"{'#':>4} {'it':>2} {'caller':<10} {'step':<34} {'model':<22} {'in':>6} {'out':>5} {'sec':>5}  output")
    for e in run:
        it = "" if e["iteration"] is None else e["iteration"]
        print(
            f"{e['seq']:>4} {it:>2} {e['caller']:<10} {one_line(e['step'], 34):<34} "
            f"{one_line(e['model'], 22):<22} {e['prompt_tokens'] or '':>6} "
            f"{e['completion_tokens'] or '':>5} {e['latency']:>5.1f}  {gist(e)}"
        )


def print_caller_stats(run: Run) -> None:
    stats: Dict[Tuple[str, str], List[int]] = defaultdict(lambda: [0, 0, 0])
    for e in run:
        s = stats[(e["caller"], e["model"])]
        s[0] += 1
        s[1] += e["prompt_tokens"] or 0
        s[2] += e["completion_tokens"] or 0
    print(f"\n{'caller':<10} {'model':<30} {'calls':>5} {'in_tok':>8} {'out_tok':>8}")
    for (caller, model), (n, tin, tout) in sorted(stats.items()):
        print(f"{caller:<10} {model:<30} {n:>5} {tin:>8} {tout:>8}")


def handoffs(run: Run) -> Tuple[Counter, Counter]:
    """
    act_order: agent A's `act` call directly followed by agent B's `act` call.
    talks: agent A opened a communication session with agent B.
    """
    act_order: Counter = Counter()
    talks: Counter = Counter()
    previous = None
    for e in run:
        if e["step"] == "act":
            if previous is not None:
                act_order[(previous, e["caller"])] += 1
            previous = e["caller"]
        for tc in e["tool_calls"]:
            if tc["name"] == "new_communication_session":
                try:
                    target = json.loads(tc["arguments"]).get("target_agent_id")
                except (TypeError, json.JSONDecodeError):
                    target = None
                talks[(e["caller"], target)] += 1
    return act_order, talks


def print_handoffs(act_order: Counter, talks: Counter) -> None:
    print("\nact order (A acts, then B acts):")
    for (a, b), n in act_order.most_common():
        print(f"  {a:>10} → {b:<10} {n}")
    print("communication sessions (A starts a chat with B):")
    for (a, b), n in talks.most_common() or [(("(none)", ""), 0)]:
        print(f"  {a:>10} → {b:<10} {n}")


def show_call(runs: List[Tuple[str, Run]], seq: int) -> None:
    for name, run in runs:
        for e in run:
            if e["seq"] != seq:
                continue
            print(f"=== {name}  #{seq}  {e['caller']}.{e['step']}  ({e['model']})")
            print("stack:", " > ".join(e["stack"]))
            if e["tools"]:
                print("tools offered:", ", ".join(map(str, e["tools"])))
            for m in e["messages"]:
                print(f"\n--- [{m['role']}]\n{m['content']}")
            print(f"\n--- [response]\n{e['response']}")
            for tc in e["tool_calls"]:
                print(f"\n--- [tool call] {tc['name']}\n{tc['arguments']}")
            print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="+", help="trace .jsonl files")
    parser.add_argument("--show", type=int, help="print the full prompt and response of call #N")
    parser.add_argument("--flow", action="store_true", help="only print hand-off counts summed over all runs")
    args = parser.parse_args()

    runs = load_runs(args.paths)
    if args.show is not None:
        show_call(runs, args.show)
        return
    if args.flow:
        act_total: Counter = Counter()
        talk_total: Counter = Counter()
        for _, run in runs:
            act_order, talks = handoffs(run)
            act_total.update(act_order)
            talk_total.update(talks)
        print(f"{len(runs)} runs")
        print_handoffs(act_total, talk_total)
        return
    for name, run in runs:
        print(f"\n##### {name}: {len(run)} LLM calls\n")
        print_timeline(run)
        print_caller_stats(run)
        print_handoffs(*handoffs(run))


if __name__ == "__main__":
    main()
