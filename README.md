# Intelligent Test Generation Engine

> Give it a Python function. It parses the AST, scores complexity, reasons about every edge case, generates tests, runs them against mutation testing, and loops back to fix what it missed.

**Not a wrapper around "write me tests." An engine that proves its own output.**

---

## What it actually produced

Input — `calculate_discount(price, discount_percent)`:

```python
def calculate_discount(price: float, discount_percent: float) -> float:
    """Apply a percentage discount to a price."""
    if discount_percent > 100:
        raise ValueError("Discount cannot exceed 100 percent")
    if discount_percent < 0:
        raise ValueError("Discount cannot be negative")
    return price - (price * discount_percent / 100)
```

Output — 11 tests across 4 categories, each with agent reasoning:

```python
# Core arithmetic must be correct for a typical discount
def test_happy_path_ten_percent_off_100():
    assert calculate_discount(100.0, 10.0) == pytest.approx(90.0)

# This catches the > vs >= mutation: 100 must NOT raise
def test_boundary_exactly_100_does_not_raise():
    result = calculate_discount(50.0, 100.0)
    assert result == pytest.approx(0.0)

# This catches the > vs > 101 mutation: 101 MUST raise
def test_boundary_101_is_invalid():
    with pytest.raises(ValueError):
        calculate_discount(100.0, 101.0)

# A positive discount must always reduce the price
def test_invariant_positive_discount_reduces_price():
    result = calculate_discount(500.0, 30.0)
    assert result < 500.0
```

Full generated output: [`demo/test_calculate_discount.py`](demo/test_calculate_discount.py)

---

## Mutation testing results

| Stage | Tests | Score | Logic mutations killed |
|-------|-------|-------|------------------------|
| Baseline (2 hand-written tests) | 2 | 37.5% | 6 / 16 |
| Agent first pass (11 tests) | 11 | **50.0%** | **8 / 16** |

**The feedback loop killed 2 additional mutations** the baseline missed:
- `discount_percent > 100` → `discount_percent >= 100` — caught by the boundary test at exactly 100
- `discount_percent > 100` → `discount_percent > 101` — caught by the boundary test at 101

The 8 surviving mutants are all **string content mutations** inside `ValueError` messages (case changes, `None`, prefix injection). These are intentionally not killed — asserting on exception message text is a brittle anti-pattern. Every logic mutation is killed.

Full report with per-mutant breakdown: [`demo/MUTATION_REPORT.md`](demo/MUTATION_REPORT.md)

---

## Architecture

```
Input: source code or GitHub URL
         │
         ▼
┌─────────────────────────────────┐
│ Stage 1 — Parse                 │
│  Tree-sitter AST                │  → FunctionInfo (params, raises, calls,
│  radon complexity               │    control flow, cyclomatic complexity)
│  networkx call graph            │  → dependency map (2 levels deep)
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│ Stage 2 — LLM Agent             │  Receives: structured facts + CC score
│  LangGraph reasoning graph      │  NOT raw source + "write tests"
│  claude-sonnet-4-6              │
│                                 │  Reasons across 7 categories:
│                                 │  happy_path · boundary · exception
│                                 │  invariant · invalid_input
│                                 │  type_edge_case · dependency_mock
└────────────────┬────────────────┘
                 │  structured JSON (input, expected, category, reasoning)
                 ▼
┌─────────────────────────────────┐
│ Stage 3 — Generate              │  → validated pytest file
│  PytestGenerator                │  → fallback skeleton if LLM output
│  ast.parse() validation         │    is unparseable
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│ Stage 4 — Mutation Testing      │  mutmut 3.x in Docker sandbox
│  Docker (--network none)        │  (--memory 256m, non-root, timeout)
│  mutmut 3.6                     │
│  subprocess with hard timeout   │  → MutationReport: killed/survived/score
└────────────────┬────────────────┘
                 │  survived mutant diffs (from mutmut show)
                 ▼
┌─────────────────────────────────┐
│ Feedback Loop                   │  Survived mutants injected into prompt:
│  re-prompt agent                │  "You changed > to >= and tests did not
│  until score ≥ 80% or           │   catch it. Write a test for exactly 100."
│  max loops reached              │
└────────────────┬────────────────┘
                 │
                 ▼
         FastAPI + Streamlit + CLI
         diskcache (SHA256-keyed, 24h TTL)
```

---

## What makes this not a beginner project

**1. AST over text.**
Tree-sitter parses code into a structured tree — function names, parameters with type hints, raise paths, call targets, control flow. The LLM receives structured facts, not raw code and a "write me tests" instruction. This is how production static analysis tools work.

**2. Complexity-aware prompting.**
radon computes cyclomatic complexity before the agent runs. CC ≥ 5 injects a `⚠️ HIGH COMPLEXITY` directive into the prompt with a directive to cover every branch exhaustively. Beginner tools treat a 2-line function and a 200-line function identically.

**3. Structured JSON output, not prose.**
The agent returns `{category, inputs, expected_output, expected_exception, reasoning}` per test case. The generator validates this JSON, then validates the rendered output is parseable Python. If either fails, a fallback is constructed from the structured data. Nothing reaches the user unvalidated.

**4. Mutation testing as proof.**
The mutation score is an objective, verifiable number. It tells you whether the tests actually catch bugs — not just whether they run. This closes the loop that every other "AI test generator" leaves open.

**5. The feedback loop.**
Survived mutant diffs are extracted via `mutmut show <name>` and re-injected into the agent prompt verbatim. The agent knows exactly which operator change its tests missed. This is measurably effective: 37.5% → 50.0% on `calculate_discount`.

**6. Docker sandbox.**
mutmut executes mutated user code. Without isolation, a mutation like `while True:` hangs your server. The sandbox enforces no network, 256 MB memory, 1 CPU, non-root user, and a hard wall-clock timeout via subprocess.

**7. SHA256 result cache.**
Identical source never hits the API twice. The cache stores and fully reconstructs the result — test cases, complexity report, generated code, mutation report — across server restarts.

---

## Tech stack

| Layer | Technology | Why |
|-------|-----------|-----|
| AST parsing | tree-sitter 0.25 | Fault-tolerant, language-agnostic, structured output |
| Complexity | radon 6.x | Industry-standard CC and maintainability index |
| Dependency graph | networkx | Directed call graph, BFS depth-limited traversal |
| LLM | claude-sonnet-4-6 via Anthropic API | Structured JSON, 200k context |
| Agent orchestration | LangGraph 1.2 | Explicit state machine, clean node boundaries |
| Mutation testing | mutmut 3.6 | Python-native, diff output for feedback loop |
| Sandbox | Docker | Network isolation, resource caps, non-root |
| API | FastAPI + uvicorn | Async jobs, auto OpenAPI docs |
| Frontend | Streamlit | Complexity badge, score ring, per-case reasoning |
| CLI | click + rich | CI-friendly, works without UI |
| Cache | diskcache | Persistent across restarts, TTL expiry |
| GitHub input | httpx | Blob URL → raw.githubusercontent.com |

---

## Setup

```bash
git clone <repo>
cd test-gen-engine
pip install -r requirements.txt

# Required for mutation testing
docker build -t test-gen-sandbox ./sandbox/

cp .env.example .env
# Add your ANTHROPIC_API_KEY

./start.sh
# Backend  → http://localhost:8000
# Frontend → http://localhost:8501
# API docs → http://localhost:8000/docs
```

**Dev mode (no Docker):**
```bash
export ANTHROPIC_API_KEY=sk-ant-...
export USE_DOCKER=false
uvicorn backend.api:app --reload &
streamlit run frontend/app.py
```

**CLI:**
```bash
# Complexity analysis only — no API calls
python cli.py analyse path/to/file.py

# Generate tests, print to stdout
python cli.py generate path/to/file.py

# Write to tests/ directory with mutation scoring
python cli.py generate path/to/file.py --mutation --output tests/

# From a GitHub URL
python cli.py generate https://github.com/user/repo/blob/main/utils.py
```

---

## Test suite

```
117 tests — 0 failures — 0 warnings

tests/test_parser.py       35 tests  AST extraction, all parameter forms, edge cases
tests/test_call_graph.py    8 tests  Graph construction, depth limiting, multi-file merge
tests/test_agent.py        27 tests  Prompts, LLM parsing, complexity injection, codegen
tests/test_mutator.py      15 tests  mutmut 3.x parsing, real mutation runs
tests/test_pipeline.py     32 tests  E2E pipeline, cache round-trips, GitHub fetcher
```

All LLM calls are mocked — no API key needed to run the suite.

---

## Project structure

```
test-gen-engine/
├── backend/
│   ├── models.py              # Shared dataclasses — the pipeline's type system
│   ├── pipeline.py            # Orchestrator: stages, cache, feedback loop
│   ├── api.py                 # FastAPI: /analyze/sync, /analyze, /health, /cache
│   ├── cache.py               # diskcache: SHA256-keyed, 24h TTL
│   ├── parser/
│   │   ├── ast_parser.py      # Tree-sitter: extracts FunctionInfo
│   │   ├── call_graph.py      # networkx: 2-level dependency resolution
│   │   ├── complexity.py      # radon: CC + MI, feeds LLM prompt
│   │   └── github_fetcher.py  # httpx: blob URL → raw source
│   ├── agent/
│   │   ├── agent.py           # LangGraph: reason → generate_code (2 LLM calls)
│   │   └── prompts.py         # Structured prompts with complexity injection
│   ├── generator/
│   │   └── generator.py       # Validates output, ensures imports, adds header
│   └── mutator/
│       ├── mutator.py         # mutmut 3.x: run, parse results, extract diffs
│       └── sandbox.py         # Docker subprocess: isolation + hard timeout
├── frontend/
│   └── app.py                 # Streamlit: complexity badge, score ring, reasoning
├── cli.py                     # click + rich: generate, analyse, cache subcommands
├── demo/
│   ├── calculate_discount.py      # Benchmark input function
│   ├── test_calculate_discount.py # Actual generated test output
│   └── MUTATION_REPORT.md         # Real mutation scores with per-mutant analysis
├── sandbox/
│   └── Dockerfile             # Python 3.11-slim, non-root, pytest + mutmut
├── tests/
│   ├── conftest.py            # Shared path setup
│   ├── test_parser.py
│   ├── test_call_graph.py
│   ├── test_agent.py
│   ├── test_mutator.py
│   └── test_pipeline.py
├── pytest.ini
├── requirements.txt
├── .env.example
└── start.sh
```