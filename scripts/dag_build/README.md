# Building a static workflow from chain runs

Run research tasks in chain mode, tag every `act` with a role, turn the observed role-to-role
transitions into a role DAG, assign each task's agents to the roles, and run the result as
**static mode**: the chain loop with the order of agents fixed in advance.
Run everything from the MARBLE root with the MARBLE venv (`.venv/bin/python`).

```bash
# 0. Chain configs for the tasks the DAG is built from
.venv/bin/python scripts/dag_build/make_configs.py --tasks 1-10

# 0'. Run them with tracing (4 at a time); traces go to result/traces/chain/task_N.jsonl
bash scripts/dag_build/run_chain.sh configs/chain 4

# 1a. Tag every act with a role (LLM)
.venv/bin/python scripts/dag_build/label_acts.py result/traces/chain/*.jsonl --show

# 1b. Role transitions -> role DAG template, scripts/dag_build/dag_template.yaml (tracked)
.venv/bin/python scripts/dag_build/build_dag.py

# 2. Assign each task's agents to the roles (LLM) -> static configs
.venv/bin/python scripts/dag_build/assign_roles.py --tasks 12-21 --out configs/static_eval --result-dir result/static_eval

# 3. Compare with chain on the same held-out tasks
.venv/bin/python scripts/dag_build/make_configs.py --tasks 12-21 --out configs/chain_eval --result-dir result/chain_eval
bash scripts/dag_build/run_chain.sh configs/chain_eval 4
bash scripts/dag_build/run_chain.sh configs/static_eval 5
.venv/bin/python scripts/dag_build/compare.py chain=result/traces/chain_eval static=result/traces/static_eval
```

## Static mode

`coordinate_mode: static` runs the chain loop unchanged except that the next agent comes from
`static.schedule` instead of the acting agent's choice. Prompts, agent ids, memory, the list of
teammates, and the planner and evaluator calls are those of chain mode; the hand-off plan prompt
only names the fixed next agent instead of asking for a choice, and the last agent writes no plan.
A static config is the task's chain config plus:

```yaml
coordinate_mode: static
static:
  schedule: [agent2, agent1, agent2, agent1, agent2]   # who acts at each step
  roles: [ideation, method_design, critique, experiment_design, writing]   # for reference
```

The schedule is a topological order of the role DAG (parallel roles run one after the other),
with each role mapped to its assigned agent. An agent holding several roles appears several
times and plays each turn as itself, with its own memory.

## Notes

- `--tasks` takes ids like `1-10` or `1,5,9`; the tasks come from `multiagentbench/research/research_main.jsonl`.
- The second argument of `run_chain.sh` is how many tasks run at the same time, not how many tasks run;
  it runs every yaml in the config directory, whatever its `coordinate_mode`. Finished traces are
  skipped on reruns.
- Roles and their descriptions are defined in `roles.yaml`. Review `dag_template.yaml`
  (editable by hand) before step 2. It is the DAG the experiments use (built from tasks 1-10)
  and is tracked in git; rebuilding it overwrites it.
- Act labels are written to `result/dag_build/act_labels.jsonl`, role assignments with the model's
  reasons to `result/dag_build/assignments.jsonl`. The model's assignments are not reproducible;
  `assign_roles.py --reuse-log` rebuilds configs from the logged ones without asking again.
- Other helpers: `compare.py` (judge scores, acts, calls, tokens and time per condition, from
  traces), `coverage.py` (how many agents of a team actually act).
