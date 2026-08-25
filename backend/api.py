"""
FastAPI layer — exposes the full pipeline as a REST API.

Routes:
  POST /analyze/sync     — synchronous (Streamlit uses this)
  POST /analyze          — async, returns job_id immediately
  GET  /results/{job_id} — poll for async results
  GET  /health           — sanity check + cache stats
  GET  /jobs             — list all jobs (debug)
  DELETE /cache          — clear the result cache
"""

from __future__ import annotations
import os
import uuid
import threading
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.pipeline import Pipeline
from backend.models import PipelineResult
from backend.cache import ResultCache

app = FastAPI(
    title="Intelligent Test Generation Engine",
    description="AST-aware · complexity-scored · mutation-tested · cached pytest generator.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    source_code: Optional[str] = None
    github_url: Optional[str] = None          # ← elite: GitHub URL support
    target_function: Optional[str] = None
    run_mutation: bool = False

    model_config = {"json_schema_extra": {"example": {
        "source_code": (
            "def calculate_discount(price: float, discount_percent: float) -> float:\n"
            "    if discount_percent > 100:\n"
            "        raise ValueError(\"Discount can't exceed 100%\")\n"
            "    if discount_percent < 0:\n"
            "        raise ValueError(\"Discount can't be negative\")\n"
            "    return price - (price * discount_percent / 100)\n"
        ),
        "target_function": None,
        "run_mutation": False,
    }}}


class ComplexityOut(BaseModel):
    cyclomatic_complexity: int
    risk_label: str
    risk_level: str
    maintainability_index: float
    recommendation: str


class ResultsResponse(BaseModel):
    job_id: str
    status: str
    cache_hit: bool = False                   # ← shown in UI as ⚡
    function_name: Optional[str] = None
    test_code: Optional[str] = None
    test_count: Optional[int] = None
    mutation_score: Optional[float] = None
    test_categories: Optional[list[str]] = None
    reasoning_summary: Optional[str] = None
    test_cases: Optional[list[dict]] = None
    survived_mutants: Optional[list[str]] = None
    complexity: Optional[ComplexityOut] = None  # ← shown as badge in UI
    error: Optional[str] = None


class AnalyzeResponse(BaseModel):
    job_id: str
    status: str
    message: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    cache_stats = ResultCache().stats()
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "anthropic_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "use_docker": os.environ.get("USE_DOCKER", "true"),
        "cache": cache_stats,
    }


@app.post("/analyze/sync", response_model=ResultsResponse)
def analyze_sync(request: AnalyzeRequest):
    """
    Synchronous pipeline — blocks until complete.
    Streamlit calls this directly. Typical: 10–30s without mutation.
    """
    pipeline = _make_pipeline()
    try:
        result = _run_request(pipeline, request)
    except Exception as e:
        result = PipelineResult(job_id="sync", status="failed", error=str(e))
    return _to_response(result)


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze_async(request: AnalyzeRequest, background_tasks: BackgroundTasks):
    """
    Async pipeline — returns job_id immediately.
    Poll GET /results/{job_id} until status == 'complete'.
    """
    job_id = str(uuid.uuid4())[:8]

    with _jobs_lock:
        _jobs[job_id] = {"status": "running"}

    background_tasks.add_task(_run_job_bg, job_id, request)

    return AnalyzeResponse(
        job_id=job_id,
        status="running",
        message=f"Job started. Poll GET /results/{job_id} for results.",
    )


@app.get("/results/{job_id}", response_model=ResultsResponse)
def get_results(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    if job.get("status") == "running":
        return ResultsResponse(job_id=job_id, status="running")
    return ResultsResponse(**job)


@app.get("/jobs")
def list_jobs():
    with _jobs_lock:
        return [{"job_id": jid, "status": j.get("status")} for jid, j in _jobs.items()]


@app.delete("/cache")
def clear_cache():
    n = ResultCache().clear()
    return {"cleared": n, "message": f"Cleared {n} cached results."}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pipeline() -> Pipeline:
    return Pipeline(
        api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        use_docker=os.environ.get("USE_DOCKER", "true").lower() == "true",
        max_feedback_loops=int(os.environ.get("MAX_FEEDBACK_LOOPS", "1")),
        use_cache=os.environ.get("USE_CACHE", "true").lower() == "true",
    )


def _run_request(pipeline: Pipeline, request: AnalyzeRequest) -> PipelineResult:
    """Dispatch to the right pipeline entry point."""
    if request.github_url:
        return pipeline.run_from_url(
            github_url=request.github_url,
            target_function=request.target_function,
            run_mutation=request.run_mutation,
        )
    elif request.source_code:
        return pipeline.run_from_source(
            source_code=request.source_code,
            target_function=request.target_function,
            run_mutation=request.run_mutation,
        )
    else:
        return PipelineResult(
            job_id="err", status="failed",
            error="Provide either source_code or github_url.",
        )


def _run_job_bg(job_id: str, request: AnalyzeRequest):
    pipeline = _make_pipeline()
    try:
        result = _run_request(pipeline, request)
        response = _to_response(result).model_dump()
    except Exception as e:
        response = {"job_id": job_id, "status": "failed", "error": str(e)}
    with _jobs_lock:
        _jobs[job_id] = response


def _to_response(result: PipelineResult) -> ResultsResponse:
    # Complexity
    complexity_out = None
    if result.function_info and result.function_info.complexity:
        c = result.function_info.complexity
        complexity_out = ComplexityOut(
            cyclomatic_complexity=c.cyclomatic_complexity,
            risk_label=c.risk_label,
            risk_level=c.risk_level,
            maintainability_index=c.maintainability_index,
            recommendation=c.recommendation,
        )

    test_cases_out = None
    if result.agent_result:
        test_cases_out = [
            {
                "category":           tc.category.value,
                "description":        tc.description,
                "inputs":             tc.inputs,
                "expected_output":    tc.expected_output,
                "expected_exception": tc.expected_exception,
                "reasoning":          tc.reasoning,
            }
            for tc in result.agent_result.test_cases
        ]

    categories = None
    if result.agent_result:
        categories = sorted({tc.category.value for tc in result.agent_result.test_cases})

    return ResultsResponse(
        job_id=result.job_id,
        status=result.status,
        cache_hit=result.cache_hit,
        function_name=result.function_info.name if result.function_info else None,
        test_code=result.generated_test.test_code if result.generated_test else None,
        test_count=result.generated_test.test_count if result.generated_test else None,
        mutation_score=result.mutation_score,
        test_categories=categories,
        reasoning_summary=(
            result.agent_result.agent_reasoning_summary if result.agent_result else None
        ),
        test_cases=test_cases_out,
        survived_mutants=(
            result.mutation_report.survived_descriptions if result.mutation_report else None
        ),
        complexity=complexity_out,
        error=result.error,
    )