# Building a role-level DAG from chain runs

Run the research tasks in chain mode, tag every `act` with a role, turn the observed
role-to-role transitions into one DAG template, then assign each task's agents to the roles.
Run everything from the MARBLE root with the MARBLE venv (`.venv/bin/python`).

```bash
# 0. 產生前十題的 chain config（已經幫你產好，在 configs/chain/）
.venv/bin/python scripts/dag_build/make_configs.py --tasks 1-10

# 0'. 跑十題 chain（同時跑 4 題），trace 存到 result/traces/chain/task_N.jsonl
bash scripts/dag_build/run_chain.sh configs/chain 4

# 1a. 用 gemma 把每次 act 標上角色
.venv/bin/python scripts/dag_build/label_acts.py result/traces/chain/*.jsonl --show

# 1b. 統計角色轉移 → 產生 DAG 範本 result/dag_build/dag_template.yaml
.venv/bin/python scripts/dag_build/build_dag.py

# 2. 每題依 profile 指派 agent → 產生 configs/dag/task_N.yaml
.venv/bin/python scripts/dag_build/assign_roles.py --tasks 1-10
```

Notes:

- `--tasks` takes ids like `1-10` or `1,5,9`; the tasks come from `multiagentbench/research/research_main.jsonl`.
- The second argument of `run_chain.sh` is how many tasks run at the same time, not how many tasks run;
  it runs every yaml in the config directory. Finished traces are skipped on reruns.
- Roles and their `dag_task` sub-tasks are defined in `roles.yaml`. Review
  `result/dag_build/dag_template.yaml` (editable by hand) before step 2.
- Act labels are written to `result/dag_build/act_labels.jsonl`, role assignments with the model's
  reasons to `result/dag_build/assignments.jsonl`.

## Matching what DAG nodes see to chain mode

In chain mode only the first agent sees the task; every later agent gets just the plan the
previous agent wrote for it, and the planner builds the answer from all agents' outputs. DAG
configs can do the same through a `dag` section (defaults keep the original behavior):

```yaml
dag:
  handoff: note      # full (default): overall task + predecessors' full outputs
                     # note: only the plan each predecessor writes for the node
  summarize: all     # sinks (default): planner sees the sink nodes; all: every node
```

`variant_configs.py` copies a config directory with such settings changed, keeping the agents,
roles and edges identical:

```bash
.venv/bin/python scripts/dag_build/variant_configs.py configs/dag_eval configs/dag_note_eval --handoff note --summarize all
bash scripts/dag_build/run_chain.sh configs/dag_note_eval 5
.venv/bin/python scripts/dag_build/compare.py chain=result/traces/chain_eval dag_full=result/traces/dag_eval dag_note=result/traces/dag_note_eval
```

Other helpers: `compare.py` (scores, tokens and time per condition), `coverage.py` (how many
agents of a team actually act).

## Static mode: chain with a fixed order

`coordinate_mode: static` runs the chain loop unchanged except that the next agent comes from
`static.schedule` instead of the acting agent's choice. Prompts, agent ids, memory, the list of
teammates, the planner and evaluator calls are those of chain mode; the hand-off plan prompt only
names the fixed next agent instead of asking for a choice, and the last agent writes no plan.
`static_configs.py` copies each chain config and adds the schedule: a topological order of the
role DAG mapped to the agents `assign_roles.py` chose (an agent holding two roles appears twice).

```bash
.venv/bin/python scripts/dag_build/static_configs.py --chain configs/chain_eval --dag configs/dag_eval --out configs/static_eval
bash scripts/dag_build/run_chain.sh configs/static_eval 5
.venv/bin/python scripts/dag_build/compare.py chain=result/traces/chain_eval static=result/traces/static_eval
```
