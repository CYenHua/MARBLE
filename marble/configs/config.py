"""
Configuration management module.
"""

from typing import Any, Dict, List

import yaml


class Config:
    """
    Configuration class to load and store system configurations.
    """

    def __init__(self, data: Dict[str, Any]):
        """
        Initialize the Config with data.

        Args:
            data (Dict[str, Any]): Configuration data.
        """
        self.environment = data.get("environment", {})
        self.relationships = data.get("relationships", [])
        self.agents = data.get("agents", [])
        self.metrics = data.get("metrics", {})
        self.llm = data.get("llm", "")
        self.tools = data.get("tools", {})
        self.logger = data.get("logger", {})
        self.parallel = data.get("parallel", {})
        self.graph = data.get("graph", {})
        self.memory = data.get("memory", {})
        self.engine_planner = data.get("engine_planner", {})
        self.task: Dict[str, Any] = data.get("task", {})
        self.coordination_mode = data.get("coordinate_mode", "centralized")
        self.relationships = data.get("relationships", [])
        self.output = data.get("output", {})
        # agent_max_tokens: max output tokens per agent LLM call (upstream: 512)
        # result_chars: chars of each agent result passed to the planner (upstream: 1000)
        limits = data.get("output_limits", {})
        self.agent_max_tokens: int = limits.get("agent_max_tokens", 512)
        self.result_chars: int = limits.get("result_chars", 1000)
        # DAG mode only.
        # handoff: what a non-root node receives besides its dag_task.
        #   full: the overall task and the full outputs of its predecessors
        #   note: only a hand-off note each predecessor writes for it (as in chain mode)
        # summarize: whose outputs the planner turns into the final answer.
        #   sinks: the nodes without successors; all: every node (as in chain mode)
        # sub_task: whether a node's prompt states its role's dag_task. With false, the role
        #   reaches the node only through the hand-off note its predecessor writes, and a
        #   node's task is exactly what the next agent gets in chain mode.
        # Static mode: chain mode with the order of agents fixed in advance (schedule), e.g.
        # a topological order of a role DAG mapped to the task's agents. roles is informative.
        static = data.get("static", {})
        self.static_schedule: List[str] = static.get("schedule", [])
        dag = data.get("dag", {})
        self.dag_handoff: str = dag.get("handoff", "full")
        self.dag_summarize: str = dag.get("summarize", "sinks")
        self.dag_sub_task: bool = dag.get("sub_task", True)

    @staticmethod
    def load(file_path: str) -> "Config":
        """
        Load configuration from a YAML file.

        Args:
            file_path (str): Path to the configuration file.

        Returns:
            Config: An instance of the Config class.

        Raises:
            FileNotFoundError: If the configuration file is not found.
            yaml.YAMLError: If there is an error parsing the YAML file.
        """
        with open(file_path, "r") as file:
            data = yaml.safe_load(file)
        return Config(data)
