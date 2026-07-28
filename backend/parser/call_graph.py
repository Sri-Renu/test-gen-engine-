"""
Call Graph Builder — Stage 1b of the pipeline.

Takes the list of FunctionInfo objects from the AST parser and builds
a directed call graph using networkx. This powers dependency resolution:
when the LLM agent analyzes a function, we can pull in its callees so
the agent has full context (not just the target function in isolation).
"""

from __future__ import annotations
from typing import Optional
import networkx as nx

from backend.models import FunctionInfo, ParseResult


class CallGraphBuilder:
    """
    Build and query a directed call graph from parsed functions.

    Nodes  = function names (str)
    Edges  = caller → callee  (directed)

    Usage:
        builder = CallGraphBuilder()
        builder.build(parse_result)
        deps = builder.get_dependencies("calculate_discount", depth=2)
    """

    def __init__(self):
        self._graph: nx.DiGraph = nx.DiGraph()
        self._function_map: dict[str, FunctionInfo] = {}

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self, parse_result: ParseResult) -> None:
        """
        Populate the graph from a ParseResult.
        Can be called multiple times to merge results from multiple files.
        """
        for fn in parse_result.functions:
            self._function_map[fn.name] = fn
            self._graph.add_node(fn.name, info=fn)

        for fn in parse_result.functions:
            for callee in fn.calls:
                self._graph.add_edge(fn.name, callee)

        # Also add any explicit edges from parse_result
        for caller, callee in parse_result.call_graph_edges:
            self._graph.add_edge(caller, callee)

    def build_from_sources(self, parse_results: list[ParseResult]) -> None:
        """Build graph from multiple ParseResult objects (multi-file)."""
        for result in parse_results:
            self.build(result)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_dependencies(
        self, function_name: str, depth: int = 2
    ) -> list[FunctionInfo]:
        """
        Return FunctionInfo objects for all callees of function_name
        up to `depth` levels deep, in call order (BFS).

        Only returns functions we actually have parsed info for.
        """
        if function_name not in self._graph:
            return []

        visited = set()
        queue = [(function_name, 0)]
        result = []

        while queue:
            current, level = queue.pop(0)
            if level >= depth:
                continue
            for neighbor in self._graph.successors(current):
                if neighbor not in visited and neighbor in self._function_map:
                    visited.add(neighbor)
                    result.append(self._function_map[neighbor])
                    queue.append((neighbor, level + 1))

        return result

    def get_callers(self, function_name: str) -> list[FunctionInfo]:
        """Return all functions that call this function."""
        callers = []
        for caller in self._graph.predecessors(function_name):
            if caller in self._function_map:
                callers.append(self._function_map[caller])
        return callers

    def get_all_function_names(self) -> list[str]:
        return list(self._function_map.keys())

    def get_function(self, name: str) -> Optional[FunctionInfo]:
        return self._function_map.get(name)

    def has_function(self, name: str) -> bool:
        return name in self._function_map

    def summary(self) -> str:
        nodes = self._graph.number_of_nodes()
        edges = self._graph.number_of_edges()
        return f"CallGraph: {nodes} functions, {edges} call edges"

    def to_dict(self) -> dict:
        """Serializable representation for debugging / UI display."""
        return {
            "nodes": list(self._graph.nodes()),
            "edges": [
                {"from": u, "to": v}
                for u, v in self._graph.edges()
            ],
        }