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
