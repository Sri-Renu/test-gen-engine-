"""
Pipeline Orchestrator — all 6 stages wired together.

  [GitHub/file] → parse → complexity → call_graph
                → agent(reason+codegen) → generator
                → [mutmut → feedback_loop]
                → PipelineResult

Elite features wired in:
  - ComplexityAnalyser: annotates every FunctionInfo; high-complexity
    functions get deeper reasoning prompts
  - GitHubFetcher: run_from_url() accepts any github.com URL
  - ResultCache: SHA256-keyed diskcache; identical inputs never hit the API twice
  - Feedback loop: survived mutants re-prompt the agent (2 extra LLM calls per loop)

Cost per run:
  Cache hit:         0 LLM calls
  No mutation:       2 LLM calls  (reason + codegen)
  With mutation:     2 + 2*N LLM calls  (N = feedback loops)
"""

from __future__ import annotations
import uuid
import os

from backend.models import (
    FunctionInfo, PipelineResult, AgentResult, GeneratedTest
)
from backend.parser.ast_parser import ASTParser
from backend.parser.call_graph import CallGraphBuilder
from backend.parser.complexity import ComplexityAnalyser
from backend.parser.github_fetcher import GitHubFetcher
from backend.agent.agent import TestGenerationAgent
from backend.generator.generator import PytestGenerator
from backend.mutator.mutator import MutationRunner
from backend.cache import ResultCache


class Pipeline:

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-6",
        use_docker: bool = True,
        max_feedback_loops: int = 1,
        use_cache: bool = True,
    ):
        self._api_key          = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._model            = model
        self._use_docker       = use_docker
        self._max_feedback_loops = max_feedback_loops

        self._ast_parser   = ASTParser()
        self._complexity   = ComplexityAnalyser()
        self._github       = GitHubFetcher()
        self._agent        = TestGenerationAgent(api_key=self._api_key, model=self._model)
        self._generator    = PytestGenerator()
        self._mutator      = MutationRunner()
        self._cache        = ResultCache() if use_cache else None

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def run_from_url(
        self,
        github_url: str,
        target_function: str | None = None,
        run_mutation: bool = False,
    ) -> PipelineResult:
        """Fetch from GitHub URL, then run the pipeline."""
        fetch = self._github.fetch(github_url)
        if not fetch.success:
            return PipelineResult(
                job_id=str(uuid.uuid4())[:8],
                status="failed",
                error=f"GitHub fetch failed: {fetch.error}",
            )
        return self.run_from_source(
            source_code=fetch.source_code,
            target_function=target_function,
            run_mutation=run_mutation,
            module_path=fetch.file_path or github_url,
        )

    def run_from_source(
        self,
        source_code: str,
        target_function: str | None = None,
        run_mutation: bool = False,
        module_path: str = "<snippet>",
    ) -> PipelineResult:
        """Main entry point: raw Python source → PipelineResult."""
        job_id = str(uuid.uuid4())[:8]

        # ── Cache check ──────────────────────────────────────────────
        if self._cache:
            key = self._cache.make_key(source_code, target_function, run_mutation)
            cached = self._cache.get(key)
            if cached:
                cached["cache_hit"] = True
                cached["job_id"]    = job_id
                return self._dict_to_result(cached, job_id)

        # ── Stage 1: Parse ───────────────────────────────────────────
        parse_result = self._ast_parser.parse_source(source_code, module_path)
        if not parse_result.functions:
            return PipelineResult(job_id=job_id, status="failed",
                                  error="No Python functions found in the source.")

        # Select target function
        if target_function:
            fn = parse_result.get_function(target_function)
            if not fn:
                available = [f.name for f in parse_result.functions]
                return PipelineResult(
                    job_id=job_id, status="failed",
                    error=f"Function '{target_function}' not found. Available: {available}",
                )
        else:
            fn = parse_result.functions[0]

        # ── Stage 1b: Complexity ─────────────────────────────────────
        fn.complexity = self._complexity.analyse_function(fn.name, source_code)

        # ── Stage 1c: Call graph (fresh build — never accumulate across runs) ─
        call_graph = CallGraphBuilder()
        call_graph.build(parse_result)
        dependencies = call_graph.get_dependencies(fn.name, depth=2)

        # Annotate dependency complexity too
        for dep in dependencies:
            dep.complexity = self._complexity.analyse_function(dep.name, source_code)

        # ── Stages 2+3: Agent + Generator ────────────────────────────
        agent_result, generated_test = self._run_agent_and_generate(
            fn, dependencies, survived_mutants=[]
        )

        result = PipelineResult(
            job_id=job_id,
            status="complete",
            function_info=fn,
            agent_result=agent_result,
            generated_test=generated_test,
        )

        if not run_mutation:
            self._maybe_cache(result, source_code, target_function, run_mutation)
            return result

        # ── Stage 4: Mutation + feedback loop ────────────────────────
        result = self._run_mutation_loop(result, source_code, fn, dependencies)
        self._maybe_cache(result, source_code, target_function, run_mutation)
        return result

    def run_from_function_info(
        self,
        fn: FunctionInfo,
        source_code: str,
        dependencies: list[FunctionInfo] | None = None,
        run_mutation: bool = False,
    ) -> PipelineResult:
        """Direct entry when fn is already parsed (tests / advanced use)."""
        job_id = str(uuid.uuid4())[:8]
        deps = dependencies or []

        if fn.complexity is None:
            fn.complexity = self._complexity.analyse_function(fn.name, source_code)

        agent_result, generated_test = self._run_agent_and_generate(
            fn, deps, survived_mutants=[]
        )
        result = PipelineResult(
            job_id=job_id, status="complete",
            function_info=fn,
            agent_result=agent_result,
            generated_test=generated_test,
        )
        if not run_mutation:
            return result
        return self._run_mutation_loop(result, source_code, fn, deps)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_agent_and_generate(
        self,
        fn: FunctionInfo,
        dependencies: list[FunctionInfo],
        survived_mutants: list[str],
    ) -> tuple[AgentResult, GeneratedTest]:
        """Single graph invocation → 2 LLM calls."""
        agent_result, raw_code = self._agent.run(
            function_info=fn,
            dependencies=dependencies,
            survived_mutants=survived_mutants,
        )
        generated_test = self._generator.build(
            agent_result=agent_result,
            raw_code=raw_code,
        )
        return agent_result, generated_test

    def _run_mutation_loop(
        self,
        result: PipelineResult,
        source_code: str,
        fn: FunctionInfo,
        dependencies: list[FunctionInfo],
    ) -> PipelineResult:
        """mutmut → survived mutants → re-prompt → repeat until score ≥ 80%."""
        current_code = result.generated_test.test_code

        for loop_i in range(self._max_feedback_loops + 1):
            report = self._mutator.run(
                function_name=fn.name,
                source_code=source_code,
                test_code=current_code,
            )
            result.mutation_report = report

            if (report.mutation_score >= 80.0
                    or not report.survived_descriptions
                    or loop_i >= self._max_feedback_loops):
                break

            agent_result, generated_test = self._run_agent_and_generate(
                fn, dependencies, report.survived_descriptions
            )
            result.agent_result   = agent_result
            result.generated_test = generated_test
            current_code          = generated_test.test_code

        result.status = "complete"
        return result

    def _maybe_cache(
        self,
        result: PipelineResult,
        source_code: str,
        target_function: str | None,
        run_mutation: bool,
    ):
        if self._cache and result.status == "complete":
            key = self._cache.make_key(source_code, target_function, run_mutation)
            self._cache.set(key, self._result_to_dict(result))

    @staticmethod
    def _result_to_dict(r: PipelineResult) -> dict:
        """Minimal serialisation for cache storage."""
        return {
            "status":     r.status,
            "cache_hit":  False,
            "function_name": r.function_info.name if r.function_info else None,
            "test_code":  r.generated_test.test_code if r.generated_test else None,
            "test_count": r.generated_test.test_count if r.generated_test else None,
            "mutation_score": r.mutation_score,
            "test_categories": sorted({
                tc.category.value for tc in r.agent_result.test_cases
            }) if r.agent_result else [],
            "reasoning_summary": (
                r.agent_result.agent_reasoning_summary if r.agent_result else ""
            ),
            "test_cases": [
                {
                    "category":          tc.category.value,
                    "description":       tc.description,
                    "inputs":            tc.inputs,
                    "expected_output":   tc.expected_output,
                    "expected_exception":tc.expected_exception,
                    "reasoning":         tc.reasoning,
                }
                for tc in r.agent_result.test_cases
            ] if r.agent_result else [],
            "survived_mutants": (
                r.mutation_report.survived_descriptions if r.mutation_report else []
            ),
            "complexity": (
                {
                    "cyclomatic_complexity": r.function_info.complexity.cyclomatic_complexity,
                    "risk_label":            r.function_info.complexity.risk_label,
                    "risk_level":            r.function_info.complexity.risk_level,
                    "maintainability_index": r.function_info.complexity.maintainability_index,
                    "recommendation":        r.function_info.complexity.recommendation,
                }
                if r.function_info and r.function_info.complexity else None
            ),
        }

    @staticmethod
    def _dict_to_result(d: dict, job_id: str) -> PipelineResult:
        """
        Reconstruct a full PipelineResult from cached dict.
        The API serialises this the same way as a live result — cache hit
        is transparent to the caller except for the cache_hit=True flag.
        """
        from backend.models import (
            FunctionInfo, ComplexityReport, AgentResult, TestCase,
            TestCategory, GeneratedTest, MutationReport,
        )

        # Rebuild FunctionInfo (minimal — only what the UI needs)
        fn_name = d.get("function_name")
        function_info = None
        if fn_name:
            complexity = None
            if d.get("complexity"):
                c = d["complexity"]
                complexity = ComplexityReport(
                    function_name=fn_name,
                    cyclomatic_complexity=c.get("cyclomatic_complexity", 1),
                    risk_level=c.get("risk_level", "low"),
                    risk_label=c.get("risk_label", "A — Simple"),
                    maintainability_index=c.get("maintainability_index", 100.0),
                    recommendation=c.get("recommendation", ""),
                )
            function_info = FunctionInfo(
                name=fn_name,
                module_path="<cache>",
                source_code="",
                complexity=complexity,
            )

        # Rebuild AgentResult + TestCases
        agent_result = None
        raw_cases = d.get("test_cases") or []
        if raw_cases or d.get("reasoning_summary"):
            cases = []
            for tc in raw_cases:
                try:
                    cases.append(TestCase(
                        category=TestCategory(tc.get("category", "happy_path")),
                        description=tc.get("description", ""),
                        inputs=tc.get("inputs", {}),
                        expected_output=tc.get("expected_output"),
                        expected_exception=tc.get("expected_exception"),
                        reasoning=tc.get("reasoning", ""),
                    ))
                except (ValueError, KeyError):
                    continue
            agent_result = AgentResult(
                function_name=fn_name or "",
                test_cases=cases,
                agent_reasoning_summary=d.get("reasoning_summary", ""),
            )

        # Rebuild GeneratedTest
        generated_test = None
        if d.get("test_code"):
            generated_test = GeneratedTest(
                function_name=fn_name or "",
                test_code=d["test_code"],
                test_count=d.get("test_count", 0),
                source_agent_result=agent_result,
            )

        # Rebuild MutationReport (minimal)
        mutation_report = None
        if d.get("mutation_score") is not None:
            mutation_report = MutationReport(
                function_name=fn_name or "",
                total_mutants=0,
                killed=0,
                survived=0,
                timed_out=0,
                mutation_score=d["mutation_score"],
                survived_descriptions=d.get("survived_mutants") or [],
            )

        return PipelineResult(
            job_id=job_id,
            status=d.get("status", "complete"),
            cache_hit=True,
            function_info=function_info,
            agent_result=agent_result,
            generated_test=generated_test,
            mutation_report=mutation_report,
        )