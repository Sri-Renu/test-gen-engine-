"""
Test Generation Agent — Stages 2 & 3 of the pipeline.

LangGraph graph with 2 nodes:
  reason → generate_code

agent.run() returns (AgentResult, raw_code_str) — one tuple, one graph
invocation, exactly 2 LLM calls (reason + codegen). No redundant calls.

The feedback loop re-enters at reason with survived mutant descriptions
injected into the prompt, pushing the model to cover what it missed.
"""

from __future__ import annotations
import json
import re
from typing import TypedDict, Optional

import anthropic
from langgraph.graph import StateGraph, START, END

from backend.models import (
    FunctionInfo, TestCase, TestCategory, AgentResult,
)
from .prompts import (
    REASONING_SYSTEM, CODEGEN_SYSTEM,
    build_reasoning_prompt, build_codegen_prompt,
)


# ---------------------------------------------------------------------------
# Graph state
# ---------------------------------------------------------------------------

class AgentState(TypedDict):
    # Inputs
    function_info: FunctionInfo
    dependencies: list[FunctionInfo]
    survived_mutants: list[str]

    # Inter-node
    test_cases: list[TestCase]
    reasoning_summary: str

    # Output
    generated_code: str
    error: Optional[str]


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class TestGenerationAgent:
    """
    Two-node LangGraph agent: reason → generate_code.

    Returns (AgentResult, raw_code_str) — the pipeline uses both
    without making any extra graph calls.

    Usage:
        agent = TestGenerationAgent(api_key="sk-ant-...")
        agent_result, raw_code = agent.run(fn_info, dependencies=[])
    """

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._graph = self._build_graph()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run(
        self,
        function_info: FunctionInfo,
        dependencies: list[FunctionInfo] | None = None,
        survived_mutants: list[str] | None = None,
        max_feedback_loops: int = 1,   # kept for API compat, unused here
    ) -> tuple[AgentResult, str]:
        """
        Run the full reasoning + codegen pipeline.
        Returns (AgentResult, raw_code_str).
        Cost: exactly 2 LLM API calls.
        """
        initial: AgentState = {
            "function_info": function_info,
            "dependencies": dependencies or [],
            "survived_mutants": survived_mutants or [],
            "test_cases": [],
            "reasoning_summary": "",
            "generated_code": "",
            "error": None,
        }

        final = self._graph.invoke(initial)

        agent_result = AgentResult(
            function_name=function_info.name,
            test_cases=final["test_cases"],
            agent_reasoning_summary=final["reasoning_summary"],
        )
        return agent_result, final["generated_code"]

    # ------------------------------------------------------------------
    # Graph
    # ------------------------------------------------------------------

    def _build_graph(self):
        graph = StateGraph(AgentState)
        graph.add_node("reason", self._node_reason)
        graph.add_node("generate_code", self._node_generate_code)
        graph.add_edge(START, "reason")
        graph.add_edge("reason", "generate_code")
        graph.add_edge("generate_code", END)
        return graph.compile()

    # ------------------------------------------------------------------
    # Node: reason
    # ------------------------------------------------------------------

    def _node_reason(self, state: AgentState) -> dict:
        prompt = build_reasoning_prompt(
            state["function_info"],
            state["dependencies"],
            state["survived_mutants"] or None,
        )

        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=4096,
                system=REASONING_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = self._strip_fences(response.content[0].text)
            parsed = json.loads(raw)
            return {
                "test_cases": self._parse_test_cases(parsed.get("test_cases", [])),
                "reasoning_summary": parsed.get("reasoning_summary", ""),
                "error": None,
            }

        except json.JSONDecodeError as e:
            return {"test_cases": [], "reasoning_summary": "", "error": f"JSON parse failed: {e}"}
        except Exception as e:
            return {"test_cases": [], "reasoning_summary": "", "error": f"LLM call failed: {e}"}

    # ------------------------------------------------------------------
    # Node: generate_code
    # ------------------------------------------------------------------

    def _node_generate_code(self, state: AgentState) -> dict:
        if state.get("error") or not state["test_cases"]:
            # Return a minimal placeholder so the pipeline doesn't hard-fail
            return {"generated_code": self._empty_test_file(state["function_info"].name)}

        prompt = build_codegen_prompt(
            state["function_info"].name,
            state["test_cases"],
            state["dependencies"],
        )

        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=4096,
                system=CODEGEN_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            code = self._strip_fences(response.content[0].text)
            return {"generated_code": code, "error": None}

        except Exception as e:
            return {
                "generated_code": self._empty_test_file(state["function_info"].name),
                "error": f"Code generation failed: {e}",
            }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _strip_fences(self, text: str) -> str:
        text = text.strip()
        text = re.sub(r"^```(?:json|python)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        return text.strip()

    def _parse_test_cases(self, raw: list[dict]) -> list[TestCase]:
        cases = []
        for tc in raw:
            try:
                cat_str = tc.get("category", "happy_path").lower()
                try:
                    category = TestCategory(cat_str)
                except ValueError:
                    category = TestCategory.HAPPY_PATH

                cases.append(TestCase(
                    category=category,
                    description=tc.get("description", ""),
                    inputs=tc.get("inputs", {}),
                    expected_output=tc.get("expected_output"),
                    expected_exception=tc.get("expected_exception"),
                    reasoning=tc.get("reasoning", ""),
                    requires_mock=tc.get("requires_mock", False),
                    mock_targets=tc.get("mock_targets", []),
                ))
            except Exception:
                continue
        return cases

    def _empty_test_file(self, fn_name: str) -> str:
        return (
            f"import pytest\n"
            f"from source import {fn_name}\n\n"
            f"# Test generation encountered an error — no cases produced.\n"
            f"# Check ANTHROPIC_API_KEY and retry.\n"
        )