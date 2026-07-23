"""
Shared data models for the Intelligent Test Generation Engine.
These flow through the entire pipeline: Parser → Agent → Generator → Mutator.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Parser output models
# ---------------------------------------------------------------------------

class ParameterKind(str, Enum):
    POSITIONAL    = "positional"
    KEYWORD       = "keyword"
    VAR_POSITIONAL = "var_positional"   # *args
    VAR_KEYWORD   = "var_keyword"        # **kwargs


@dataclass
class Parameter:
    name: str
    kind: ParameterKind = ParameterKind.POSITIONAL
    type_hint: Optional[str] = None
    default_value: Optional[str] = None


@dataclass
class RaisedError:
    exception_type: str
    condition_snippet: str


@dataclass
class ComplexityReport:
    function_name: str
    cyclomatic_complexity: int
    risk_level: str          # "low" | "moderate" | "high" | "very_high"
    risk_label: str          # "A — Simple", "B — Moderate", etc.
    maintainability_index: float
    recommendation: str

    @property
    def needs_deep_testing(self) -> bool:
        return self.cyclomatic_complexity >= 5


@dataclass
class FunctionInfo:
    """Everything the parser extracts about a single Python function."""
    name: str
    module_path: str
    source_code: str
    parameters: list[Parameter] = field(default_factory=list)
    return_type_hint: Optional[str] = None
    raises: list[RaisedError] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    has_loops: bool = False
    has_conditionals: bool = False
    docstring: Optional[str] = None
    start_line: int = 0
    end_line: int = 0
    complexity: Optional[ComplexityReport] = None   # ← wired in now

    def summary(self) -> str:
        params = ", ".join(
            f"{p.name}: {p.type_hint or '?'}" for p in self.parameters
        )
        return f"{self.name}({params}) -> {self.return_type_hint or '?'}"


@dataclass
class ParseResult:
    functions: list[FunctionInfo] = field(default_factory=list)
    call_graph_edges: list[tuple[str, str]] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)

    def get_function(self, name: str) -> Optional[FunctionInfo]:
        for f in self.functions:
            if f.name == name:
                return f
        return None


# ---------------------------------------------------------------------------
# Agent output models
# ---------------------------------------------------------------------------

class TestCategory(str, Enum):
    HAPPY_PATH     = "happy_path"
    BOUNDARY       = "boundary"
    INVALID_INPUT  = "invalid_input"
    TYPE_EDGE_CASE = "type_edge_case"
    INVARIANT      = "invariant"
    EXCEPTION      = "exception"
    DEPENDENCY_MOCK = "dependency_mock"


@dataclass
class TestCase:
    category: TestCategory
    description: str
    inputs: dict
    expected_output: Optional[str]
    expected_exception: Optional[str]
    reasoning: str
    requires_mock: bool = False
    mock_targets: list[str] = field(default_factory=list)


@dataclass
class AgentResult:
    function_name: str
    test_cases: list[TestCase] = field(default_factory=list)
    agent_reasoning_summary: str = ""


# ---------------------------------------------------------------------------
# Generator output models
# ---------------------------------------------------------------------------

@dataclass
class GeneratedTest:
    function_name: str
    test_code: str
    test_count: int = 0
    source_agent_result: Optional[AgentResult] = None


# ---------------------------------------------------------------------------
# Mutator output models
# ---------------------------------------------------------------------------

@dataclass
class MutantResult:
    mutant_id: str
    status: str
    description: str
    diff_snippet: str


@dataclass
class MutationReport:
    function_name: str
    total_mutants: int
    killed: int
    survived: int
    timed_out: int
    mutation_score: float
    mutant_results: list[MutantResult] = field(default_factory=list)
    survived_descriptions: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Full pipeline result
# ---------------------------------------------------------------------------

@dataclass
class PipelineResult:
    job_id: str
    status: str                          # "complete" | "failed" | "running"
    function_info: Optional[FunctionInfo] = None
    agent_result: Optional[AgentResult] = None
    generated_test: Optional[GeneratedTest] = None
    mutation_report: Optional[MutationReport] = None
    error: Optional[str] = None
    cache_hit: bool = False              # ← shown in UI as ⚡ Cache hit

    @property
    def mutation_score(self) -> Optional[float]:
        return self.mutation_report.mutation_score if self.mutation_report else None