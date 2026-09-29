# Interview Q&A — Intelligent Test Generation Engine

Every answer below is backed by real code, real numbers, or real design
decisions. Nothing is fabricated. Where live API output is referenced,
the exact source input and expected output are documented in `demo/`.

---

## SECTION 1 — What does the project do?

**"Explain this project in 30 seconds."**

You give it a Python function. It reads the structure of the code using
a real parser — not regex, not the LLM — extracts facts about parameters,
raise paths, and dependencies. It scores complexity using radon. It sends
those structured facts to Claude, which reasons about every category of
test: happy path, boundaries, invariants, exceptions, type edge cases. It
generates a pytest file, validates it is runnable Python, then executes it
against mutation testing — a tool that intentionally breaks your code in
small ways to check whether your tests would catch real bugs. If the score
is low, it feeds the surviving mutations back to Claude and generates better
tests. The final output is a scored, validated pytest file.

---

**"What problem does it solve?"**

Developers skip edge cases because systematically thinking of all the ways
code can break is hard and tedious. AI tools that just say "write me tests"
produce 3 happy-path cases that pass but catch nothing. This engine reasons
before generating — it uses the AST structure, complexity score, and
dependency context to produce tests that are actually rigorous, then proves
their rigour with mutation testing. The mutation score is an objective,
verifiable number. You cannot fake it.

---

**"What is mutation testing? Why does it matter here?"**

Mutation testing automatically introduces small bugs into your source code —
changing `>` to `>=`, flipping `+` to `-`, returning `None` instead of a
value — and checks whether your tests catch them. If tests pass on broken
code, they are not testing the right thing.

It matters here because it closes the loop every other AI test generator
leaves open. Generating tests is easy. Proving they are good tests is hard.
The mutation score is the proof.

On `calculate_discount` with 16 mutants:
- Baseline (2 hand-written tests): 37.5% (6/16 killed)
- After agent generation (11 tests): 50.0% (8/16 killed)
- Logic mutation kill rate: **100%** — every logic mutation is killed
- The 8 surviving mutants are all string content mutations inside
  `ValueError` messages, which are intentionally not asserted on

---

## SECTION 2 — Architecture questions

**"Walk me through the architecture."**

Six stages, each with a clear input and output type:

1. **Parse** — Tree-sitter reads the source into a `FunctionInfo` dataclass:
   parameter names and type hints, return type, all `raise` statements,
   all function calls, control flow flags. A `CallGraphBuilder` maps
   dependencies up to 2 levels deep using networkx.

2. **Complexity** — radon computes cyclomatic complexity (number of
   independent paths) and maintainability index. CC ≥ 5 injects a
   `⚠️ HIGH COMPLEXITY` directive into the LLM prompt. The agent generates
   more tests for harder functions.

3. **Agent** — A LangGraph graph with two nodes: `reason` and
   `generate_code`. The `reason` node sends structured facts (not raw
   source) to Claude and receives structured JSON back:
   `{category, inputs, expected_output, expected_exception, reasoning}` per
   test case. The `generate_code` node sends those structured cases to
   Claude for code generation. Two LLM calls per run. No more.

4. **Generator** — `ast.parse()` validates the generated code is runnable
   Python. Missing imports are injected. If the LLM returns broken syntax,
   a fallback skeleton is constructed from the structured test cases.

5. **Mutator** — mutmut 3.x runs in a Docker container with
   `--network none`, 256 MB memory cap, 1 CPU, and a hard subprocess
   timeout. Survived mutant diffs are extracted via `mutmut show`.

6. **Feedback loop** — Survived diffs are injected into the reasoning
   prompt verbatim: "You changed `> 100` to `>= 100` and your tests did
   not catch it. Write a test targeting exactly 100." The agent reruns.

**"Why LangGraph? Why not just call the API directly?"**

LangGraph makes the agent a typed state machine with explicit nodes and
edges. The state is a `TypedDict` — every field has a declared type. When
something goes wrong you can inspect exactly which node failed and what
state it had. A direct API call gives you a string; you have no structure
around error recovery, retry logic, or future expansion (adding a
reflection node, a self-critique node, a tool-use node). LangGraph also
makes it easy to add the feedback loop as a conditional edge without
rewriting the core flow.

---

**"Why Tree-sitter instead of Python's built-in `ast` module?"**

Three reasons. First, fault tolerance: Python's `ast` module raises
`SyntaxError` and gives you nothing on broken code. Tree-sitter gives you
a partial tree — you can still extract the function name and parameters
even if there is a syntax error in the body. Second, Tree-sitter is
language-agnostic — the same architecture extends to JavaScript, TypeScript,
Go with a different grammar. Third, Tree-sitter works at the byte level and
gives exact byte positions, not just line numbers, which is useful for
extracting precise source snippets for mutation diffs.

---

**"Why not just pass the raw source code to Claude and ask it to write tests?"**

That is the beginner version. The problems with it:

1. Claude sees tokens, not structure. It can miss raise paths buried in
   nested conditionals, silently ignore type hints, or misidentify what
   a function actually calls.
2. There is no verification. Claude says "here are your tests" and you
   have no idea if they are good.
3. No complexity signal. Claude treats a 200-line function with 15 branches
   the same as a 5-line function with no conditionals.
4. No dependency context. If your function calls `apply_tax()`, Claude
   does not know what `apply_tax` does unless you paste everything manually.

This engine separates concerns: the parser extracts facts, the complexity
tool scores risk, the agent reasons from structured inputs, the generator
validates output, the mutator proves quality.

---

**"How does the Docker sandbox work and why is it necessary?"**

mutmut mutates your source code and then executes it. Without a sandbox,
a mutation like changing `i += 1` to `i -= 1` in a loop creates
`while True:` and hangs your server permanently. A mutation that calls
`os.system()` runs arbitrary shell commands.

The sandbox is a Docker container built from `sandbox/Dockerfile`:
- Base: `python:3.11-slim`
- Non-root user: `sandbox`
- Flags: `--network none` (no internet), `--memory 256m`, `--cpus 1.0`
- The source file and test file are volume-mounted into `/sandbox`
- A hard `timeout=` on the subprocess kills the container if mutmut hangs

This is the same isolation model used by judge systems in competitive
programming — execute untrusted code in a constrained environment with
hard resource limits.

---

**"How does the cache work?"**

`ResultCache` wraps `diskcache` with a SHA256 key derived from the source
code, target function name, and `run_mutation` flag:

```python
payload = json.dumps({
    "source": source_code.strip(),
    "target": target_function or "",
    "mutation": run_mutation,
}, sort_keys=True)
key = "v1:" + hashlib.sha256(payload.encode()).hexdigest()
```

On a cache hit, the full result is reconstructed from the stored dict —
test cases, complexity report, generated code, mutation report — and
returned with `cache_hit=True`. Zero LLM calls. Results persist across
server restarts with a 24-hour TTL.

The prefix `v1:` allows cache invalidation by bumping the version if the
result schema changes.

---

## SECTION 3 — Results and numbers

**"What mutation score did it achieve?"**

On `calculate_discount` with 16 mutants generated by mutmut 3.6:

| Tests | Score | Logic killed |
|-------|-------|-------------|
| 2 (baseline) | 37.5% | 6/8 logic mutants |
| 11 (agent) | 50.0% | 8/8 logic mutants |

50.0% is the correct ceiling for this function. The 8 surviving mutants
are all string content mutations inside `ValueError` messages. These
intentionally survive — asserting on exception message text is a brittle
anti-pattern. Every logic mutation (operator changes, arithmetic flips,
condition deletions) is killed.

---

**"Show me the tests it generated."**

See `demo/test_calculate_discount.py`. Key examples:

```python
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

These tests run and pass: 11/11. Run them:
```bash
cd demo && pytest test_calculate_discount.py -v
```

---

**"Did the feedback loop actually improve the score?"**

Yes. Measurably. Baseline with 2 hand-written tests: 37.5%. The two
logic mutations that survived the baseline were:
- `discount_percent > 100` → `discount_percent >= 100`
- `discount_percent > 100` → `discount_percent > 101`

The feedback loop extracted these diffs and re-injected them into the
agent prompt. The agent generated:
- `test_boundary_exactly_100_does_not_raise` → kills the `>=` mutation
- `test_boundary_101_is_invalid` → kills the `> 101` mutation

Score after: 50.0%. Both logic survivors killed.

---

**"How many tests does it generate per function?"**

For `calculate_discount` (CC=3, 2 raise paths, no loops):
- Agent generated 11 tests across 4 categories
- Distribution: 2 happy path, 5 boundary, 2 exception, 2 invariant

For a higher-complexity function (CC ≥ 5), the `HIGH COMPLEXITY` directive
in the prompt produces more tests — typically 15–20. The prompt instructs
the agent: "Every conditional arm needs its own test case."

---

**"How long does a run take?"**

- AST parse + complexity: < 1ms (measured: 0.19ms parse, 0.45ms complexity)
- LLM reasoning call: 3–8 seconds (network + generation time)
- LLM codegen call: 3–8 seconds
- Total without mutation: **8–20 seconds**
- With mutation testing: add 2–5 minutes (mutmut runs pytest against each
  mutant sequentially; 16 mutants × ~10s each)
- Cache hit: **< 5ms**

---

**"What does it cost to run?"**

claude-sonnet-4-6 pricing: $3/M input tokens, $15/M output tokens.
Per run (estimated 2,000 input + 1,400 output tokens):

```
Cost = (2000/1M × $3) + (1400/1M × $15) = $0.006 + $0.021 = ~$0.027
     = ~₹2.27 per run
```

Anthropic gives $5 free credits on signup = ~185 free runs.
100 runs = ~$2.70 = ~₹227.

---

**"How does it handle a function with no type hints?"**

The parser still extracts the function. Parameters without type hints are
marked `type_hint=None` in `FunctionInfo`. The prompt shows them as
`param_name: ?`. The agent infers likely types from usage — if the code
does `price * discount_percent / 100`, it infers numeric types. The
`TYPE_EDGE_CASE` category specifically prompts the agent to consider what
happens when wrong types are passed.

---

**"How does it handle multi-file projects / dependencies?"**

The call graph builder uses networkx to map which functions call which
other functions. When the pipeline runs on `calculate_discount`, it calls
`get_dependencies(fn.name, depth=2)` which walks the call graph 2 levels
deep and returns `FunctionInfo` objects for each dependency. These are
appended to the prompt as "Dependency context" with their full source.

For the GitHub URL input: the fetcher retrieves the raw file. For
multi-file projects (coming in a later version), each file would be parsed
separately and merged into the same call graph via `build_from_sources()`.

---

**"What happens if Claude returns broken JSON or broken Python?"**

Two fallbacks, each at a different stage:

1. If `json.loads()` fails on the reasoning response: `test_cases = []`,
   `error` is set on the state, `generate_code` detects it and returns
   an empty placeholder file. The pipeline returns a failed result with
   the error message, not a crash.

2. If `ast.parse()` fails on the generated code: `PytestGenerator` builds
   a fallback skeleton directly from the structured `TestCase` list — it
   constructs `def test_...():` functions programmatically from the JSON
   data, bypassing the LLM code output entirely.

Both paths are tested: `test_agent_handles_malformed_json` and
`test_fallback_on_syntax_error` in `tests/test_agent.py`.

---

## SECTION 4 — Design decisions

**"Why structured output instead of asking Claude to write the test file directly in one call?"**

Two reasons.

First, quality. When Claude is asked to "write tests," it writes code. When
it is asked to "reason about what scenarios need testing and return JSON,"
it reasons. Separating reasoning from code generation produces better tests
because the model focuses on one task at a time. The reasoning JSON also
contains the `reasoning` field — the agent explains why each test matters.
This shows up in the UI.

Second, reliability. Structured JSON can be validated and fallen back on.
A direct code response cannot — if it is broken Python, you have nothing.
With structured output, you have the test case data and can generate
fallback code from it programmatically.

---

**"Why is the call graph rebuilt fresh on every pipeline run?"**

Early implementation stored `CallGraphBuilder` as `self._call_graph` on the
`Pipeline` instance and called `.build()` on every run. Since `.build()`
adds to the existing graph rather than replacing it, after 3 runs the graph
contained functions from all 3 previous inputs mixed together.
`get_dependencies()` would return stale nodes from previous runs.

Fixed: `CallGraphBuilder()` is instantiated fresh inside `run_from_source`
on every call. No shared state between runs.

---

**"What is cyclomatic complexity and why does it change what the agent does?"**

Cyclomatic complexity (CC) counts the number of independent paths through
a function. Every `if`, `elif`, `for`, `while`, `and`, `or`, and `except`
adds one. A function with CC=1 has one path. CC=10 has ten.

radon classifies CC into risk levels:
- 1–4: A (Simple) — focus on happy path and basic boundaries
- 5–9: B (Moderate) — prioritise boundary conditions and every branch
- 10–14: C (Complex) — exhaustive testing required
- 15+: D (Unmaintainable) — refactor before testing

When CC ≥ 5, the agent prompt includes:
```
⚠️ HIGH COMPLEXITY — you MUST cover every branch path exhaustively.
Generate more test cases than you normally would.
Every conditional arm needs its own test case.
```

This produces meaningfully more thorough tests for harder functions.

---

**"What is the maintainability index and what does the number mean?"**

radon's maintainability index (MI) is a composite score on a 0–100 scale,
derived from cyclomatic complexity, Halstead volume (a measure of code
size), and lines of code. Higher is better.

- MI ≥ 65: maintainable (shown in green in the UI)
- MI 40–65: moderate concern (amber)
- MI < 40: difficult to maintain (red)

`calculate_discount` scores MI=69.2 — clean, maintainable, low risk.
The UI shows this as a metric card alongside the CC badge. It gives
reviewers an at-a-glance sense of code quality before they look at the
generated tests.

---

## SECTION 5 — Code quality and testing

**"How do you test a project that calls an LLM?"**

Every LLM call in the test suite is mocked using `unittest.mock.patch`.
The mock returns pre-defined JSON strings (for reasoning) and pre-defined
Python strings (for code generation). This means:

- Tests are deterministic — same result every run
- Tests are free — zero API calls
- Tests run in ~2–3 minutes instead of 30+ minutes
- Tests cover failure cases (malformed JSON, broken Python, API errors)
  that are hard to reproduce with real API calls

The real LLM behaviour is tested by running the pipeline manually with an
API key. The mock tests verify the pipeline wiring, the fallback logic,
the cache behaviour, and the mutation testing integration.

---

**"How many tests are in the suite?"**

117 tests across 5 files, zero failures, zero warnings:

| File | Tests | What it covers |
|------|-------|----------------|
| test_parser.py | 35 | AST extraction: params, type hints, raises, calls, loops |
| test_call_graph.py | 8 | Graph construction, depth limiting, multi-file merge |
| test_agent.py | 27 | Prompts, complexity injection, JSON parsing, codegen |
| test_mutator.py | 15 | mutmut 3.x output parsing, real mutation runs |
| test_pipeline.py | 32 | E2E, cache round-trips, GitHub fetcher, complexity wiring |

Run them:
```bash
pytest tests/ -v
# 117 passed in ~2m30s
```

---

**"What was the hardest bug you fixed?"**

The cache reconstruction bug. When a cache hit occurred, `_dict_to_result`
was a 4-line stub that discarded everything — the test cases, the generated
code, the complexity report, the mutation report. It returned a
`PipelineResult` with every field `None` except `job_id` and `status`.

The symptom was subtle: first run worked perfectly, second run (cache hit)
returned an empty UI with no tests, no reasoning, no code. It looked like
the cache was working (correct job_id, status="complete") but the result
was hollow.

Fix: rewrote `_dict_to_result` to fully reconstruct `FunctionInfo`,
`ComplexityReport`, `AgentResult`, all `TestCase` objects, `GeneratedTest`,
and `MutationReport` from the stored dict. Added 5 dedicated cache
round-trip tests that assert every field is preserved across a cache hit.

---

**"What would you add if you had more time?"**

In order of impact:

1. **Async generation across all functions in a file.** Currently the
   pipeline targets one function per run. A file with 20 functions should
   be parallelised — generate tests for all of them concurrently and return
   a test file per function plus a combined suite.

2. **Self-critique node in the LangGraph graph.** After generating test
   cases but before code generation, add a third node that reviews the
   test cases against the source and flags gaps: "You have no test for
   the case where price is 0." This would push the agent to catch its own
   blind spots.

3. **Type inference for un-annotated parameters.** Currently, parameters
   without type hints are shown as `?`. A type inference pass using the
   operations performed on each parameter (division implies numeric, `.split()`
   implies string) would produce better test inputs.

4. **Support for class methods.** The current parser correctly extracts
   methods and skips `self`/`cls`, but the pipeline does not yet handle
   fixture setup for tests that require class instantiation.

5. **Multi-file GitHub support.** Currently fetches one file. A repo-wide
   mode would clone the repo, build the call graph across all files, and
   let the agent follow dependencies across module boundaries.