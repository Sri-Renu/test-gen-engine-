"""
Intelligent Test Generation Engine — Streamlit Frontend
Elite UI: complexity badge, cache indicator, GitHub URL input,
multi-function selector, mutation score ring, per-case reasoning.
"""

import streamlit as st
import requests
import time

st.set_page_config(
    page_title="TestGen Engine",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Design system
# ---------------------------------------------------------------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Inter:wght@400;500;600&display=swap');
:root {
  --bg:#0d0f12;--surface:#151820;--surface2:#1c2029;--border:#2a2f3d;
  --accent:#5b8dee;--green:#3dd68c;--amber:#f5a623;--red:#e05c5c;
  --text:#e2e6f0;--muted:#6b7590;--code:#111318;
  --mono:'JetBrains Mono',monospace;--sans:'Inter',sans-serif;
}
html,body,[class*="css"]{background:var(--bg)!important;color:var(--text)!important;font-family:var(--sans)!important;}
#MainMenu,footer,header{visibility:hidden;}
.block-container{padding:2rem 2rem 4rem!important;max-width:1300px;}
[data-testid="stSidebar"]{background:var(--surface)!important;border-right:1px solid var(--border)!important;}
[data-testid="stSidebar"] .block-container{padding:1.5rem 1rem!important;}

/* Buttons */
.stButton>button{background:var(--accent)!important;color:#fff!important;border:none!important;
  border-radius:6px!important;font-family:var(--mono)!important;font-size:0.82rem!important;
  font-weight:700!important;letter-spacing:0.05em!important;padding:0.6rem 1.4rem!important;
  text-transform:uppercase!important;transition:opacity 0.15s!important;}
.stButton>button:hover{opacity:0.8!important;}

/* Text areas / inputs */
.stTextArea textarea,.stTextInput>div>div>input{background:var(--code)!important;
  color:var(--text)!important;border:1px solid var(--border)!important;border-radius:8px!important;
  font-family:var(--mono)!important;font-size:0.82rem!important;}
.stTextArea textarea:focus,.stTextInput>div>div>input:focus{border-color:var(--accent)!important;}

/* Code blocks */
.stCodeBlock,pre{background:var(--code)!important;border:1px solid var(--border)!important;border-radius:8px!important;}

/* Selectbox */
.stSelectbox>div>div{background:var(--surface)!important;color:var(--text)!important;
  border:1px solid var(--border)!important;border-radius:6px!important;font-family:var(--mono)!important;}

/* Tabs */
.stTabs [data-baseweb="tab-list"]{background:transparent!important;border-bottom:1px solid var(--border)!important;}
.stTabs [data-baseweb="tab"]{background:transparent!important;color:var(--muted)!important;
  font-family:var(--mono)!important;font-size:0.75rem!important;font-weight:600!important;
  text-transform:uppercase!important;letter-spacing:0.06em!important;padding:0.6rem 1.2rem!important;}
.stTabs [aria-selected="true"]{color:var(--accent)!important;border-bottom:2px solid var(--accent)!important;}

/* Section headers */
.sh{font-family:var(--mono);font-size:0.68rem;color:var(--muted);text-transform:uppercase;
  letter-spacing:0.12em;border-bottom:1px solid var(--border);padding-bottom:0.4rem;margin:1.2rem 0 0.8rem;}

/* Metric cards */
.mc{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:1.1rem 1.3rem;height:100%;}
.mc-label{font-family:var(--mono);font-size:0.65rem;color:var(--muted);text-transform:uppercase;letter-spacing:0.1em;margin-bottom:0.3rem;}
.mc-val{font-family:var(--mono);font-size:1.9rem;font-weight:700;line-height:1;}
.mc-sub{font-family:var(--mono);font-size:0.68rem;color:var(--muted);margin-top:0.25rem;}

/* Complexity badge */
.badge{display:inline-block;font-family:var(--mono);font-size:0.62rem;font-weight:700;
  letter-spacing:0.08em;text-transform:uppercase;padding:0.22rem 0.55rem;border-radius:4px;}
.badge-low{background:rgba(61,214,140,.15);color:var(--green);}
.badge-moderate{background:rgba(245,166,35,.15);color:var(--amber);}
.badge-high{background:rgba(224,92,92,.15);color:var(--red);}
.badge-very_high{background:rgba(224,92,92,.25);color:var(--red);}
.badge-cache{background:rgba(91,141,238,.15);color:var(--accent);}

/* Score ring */
.score-wrap{display:flex;align-items:center;gap:1.3rem;background:var(--surface);
  border:1px solid var(--border);border-radius:10px;padding:1.1rem 1.3rem;margin-bottom:1.2rem;}
.score-circle{width:76px;height:76px;border-radius:50%;display:flex;align-items:center;
  justify-content:center;font-family:var(--mono);font-size:1.15rem;font-weight:700;flex-shrink:0;}
.score-lbl{font-family:var(--mono);font-size:0.65rem;color:var(--muted);
  text-transform:uppercase;letter-spacing:0.1em;margin-bottom:0.25rem;}
.score-title{font-family:var(--mono);font-size:1.2rem;font-weight:700;}
.score-desc{font-size:0.8rem;color:var(--muted);margin-top:0.15rem;}

/* Case cards */
.cc{background:var(--surface);border:1px solid var(--border);border-left:3px solid var(--accent);
  border-radius:8px;padding:0.9rem 1.1rem;margin-bottom:0.65rem;}
.cc.gl{border-left-color:var(--green);}
.cc.ar{border-left-color:var(--amber);}
.cc.rd{border-left-color:var(--red);}
.cc-desc{font-size:0.87rem;font-weight:500;color:var(--text);margin-bottom:0.3rem;}
.cc-inp{font-family:var(--mono);font-size:0.74rem;color:var(--green);margin-top:0.3rem;}
.cc-why{font-size:0.79rem;color:var(--muted);line-height:1.5;margin-top:0.3rem;}

/* Pipeline steps (sidebar) */
.ps{display:flex;align-items:center;gap:0.6rem;padding:0.45rem 0;border-bottom:1px solid var(--border);}
.ps:last-child{border:none;}
.dot{width:7px;height:7px;border-radius:50%;flex-shrink:0;}
.dot.done{background:var(--green);}
.dot.pending{background:var(--border);}
.ps-name{font-family:var(--mono);font-size:0.78rem;color:var(--text);}
.ps-sub{font-family:var(--mono);font-size:0.68rem;color:var(--muted);margin-left:auto;}

::-webkit-scrollbar{width:5px;height:5px;}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px;}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BACKEND_URL = "http://localhost:8000"

EXAMPLES = {
    "calculate_discount": '''def calculate_discount(price: float, discount_percent: float) -> float:
    """Apply a percentage discount to a price."""
    if discount_percent > 100:
        raise ValueError("Discount can't exceed 100%")
    if discount_percent < 0:
        raise ValueError("Discount can't be negative")
    return price - (price * discount_percent / 100)
''',
    "find_top_k": '''def find_top_k(nums: list, k: int) -> list:
    """Return the k largest elements in descending order."""
    if not nums:
        raise ValueError("Input list cannot be empty")
    if k <= 0:
        raise ValueError("k must be positive")
    if k > len(nums):
        k = len(nums)
    return sorted(nums, reverse=True)[:k]
''',
    "parse_date": '''def parse_date(date_str: str, fmt: str = "%Y-%m-%d") -> tuple:
    """Parse a date string and return (year, month, day) tuple."""
    from datetime import datetime
    if not date_str or not date_str.strip():
        raise ValueError("date_str cannot be empty")
    try:
        dt = datetime.strptime(date_str.strip(), fmt)
        return (dt.year, dt.month, dt.day)
    except ValueError:
        raise ValueError(f"Cannot parse '{date_str}' with format '{fmt}'")
''',
}

CATEGORY_META = {
    "happy_path":      ("HAPPY",     "badge-low",      "gl", "🟦"),
    "boundary":        ("BOUNDARY",  "badge-low",      "gl", "🟩"),
    "invalid_input":   ("INVALID",   "badge-high",     "rd", "🟥"),
    "type_edge_case":  ("TYPE",      "badge-moderate", "ar", "🟨"),
    "invariant":       ("INVARIANT", "badge-low",      "gl", "🔷"),
    "exception":       ("EXCEPTION", "badge-high",     "rd", "🔴"),
    "dependency_mock": ("MOCK",      "badge-moderate", "ar", "🟧"),
}

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("""
    <div style="font-family:var(--mono);font-size:1rem;font-weight:700;color:var(--accent);
      letter-spacing:0.08em;text-transform:uppercase;">TestGen</div>
    <div style="font-family:var(--mono);font-size:0.68rem;color:var(--muted);
      letter-spacing:0.1em;text-transform:uppercase;margin-bottom:1rem;">Engine v1.0</div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="sh">Configuration</div>', unsafe_allow_html=True)
    backend_url = st.text_input("Backend URL", value=BACKEND_URL, label_visibility="collapsed")
    run_mutation = st.checkbox("Run mutation testing", value=False,
        help="Scores test quality via mutmut. Requires Docker. Adds ~2-3 min.")

    # Drive GitHub mode from session state so checkbox and example buttons stay in sync
    use_github = st.checkbox(
        "Use GitHub URL",
        value=st.session_state.get("use_github", False),
        help="Paste a GitHub URL instead of source code",
    )
    st.session_state["use_github"] = use_github  # keep state authoritative

    st.markdown('<div class="sh">Examples</div>', unsafe_allow_html=True)
    for name in EXAMPLES:
        if st.button(f"  {name}", use_container_width=True):
            st.session_state["code_input"] = EXAMPLES[name]
            st.session_state["use_github"] = False

    # Pipeline stage indicators
    st.markdown('<div class="sh">Pipeline</div>', unsafe_allow_html=True)
    has_result = "last_result" in st.session_state
    stages = [
        ("AST Parser",         "tree-sitter + networkx"),
        ("Complexity Analyser","radon cyclomatic CC"),
        ("Call Graph",         "2-level dep resolution"),
        ("LLM Agent",          "reason → structured JSON"),
        ("Pytest Generator",   "validated test file"),
        ("Mutation Testing",   "mutmut 3.x" if run_mutation else "disabled"),
        ("Feedback Loop",      "survived → re-prompt" if run_mutation else "disabled"),
        ("Cache",              "diskcache SHA256"),
    ]
    for name, desc in stages:
        dot = "done" if has_result else "pending"
        if name in ("Mutation Testing", "Feedback Loop") and not run_mutation:
            dot = "pending"
        st.markdown(f"""
        <div class="ps">
          <div class="dot {dot}"></div>
          <div><div class="ps-name">{name}</div></div>
          <div class="ps-sub">{desc}</div>
        </div>""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.markdown("""
<div style="border-bottom:1px solid var(--border);padding-bottom:1.2rem;margin-bottom:1.8rem;">
  <div style="font-family:var(--mono);font-size:1.9rem;font-weight:700;letter-spacing:-0.02em;">
    Intelligent <span style="color:var(--accent)">Test Generation</span> Engine
  </div>
  <div style="font-family:var(--mono);font-size:0.78rem;color:var(--muted);margin-top:0.4rem;">
    AST-aware &nbsp;·&nbsp; Complexity-scored &nbsp;·&nbsp; LLM-reasoned &nbsp;·&nbsp; Mutation-tested &nbsp;·&nbsp; Cached
  </div>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------
col_in, col_opt = st.columns([3, 1])

with col_in:
    st.markdown('<div class="sh">Input</div>', unsafe_allow_html=True)
    if st.session_state.get("use_github", False):
        github_url = st.text_input(
            "github_url", label_visibility="collapsed",
            placeholder="https://github.com/user/repo/blob/main/path/to/file.py",
        )
        code_input = None
    else:
        github_url = None
        code_input = st.text_area(
            "source", label_visibility="collapsed",
            value=st.session_state.get("code_input", EXAMPLES["calculate_discount"]),
            height=240, placeholder="Paste Python function here…",
        )

with col_opt:
    st.markdown('<div class="sh">Target function</div>', unsafe_allow_html=True)
    target_fn = st.text_input("fn", label_visibility="collapsed",
        placeholder="auto-detect",
        help="Leave blank to test the first function found")
    st.markdown("<br>", unsafe_allow_html=True)
    run_btn = st.button("▶  Generate Tests", use_container_width=True)

# ---------------------------------------------------------------------------
# Backend health
# ---------------------------------------------------------------------------
def check_backend(url):
    try:
        return requests.get(f"{url}/health", timeout=3).status_code == 200
    except Exception:
        return False

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if run_btn:
    payload_ok = (github_url and github_url.strip()) or (code_input and code_input.strip())
    if not payload_ok:
        st.error("Paste a Python function or enter a GitHub URL first.")
    elif not check_backend(backend_url):
        st.error(f"Backend not reachable at `{backend_url}`. Run: `./start.sh`")
    else:
        with st.spinner("Running pipeline…"):
            t0 = time.time()
            try:
                payload = {
                    "target_function": target_fn.strip() or None,
                    "run_mutation": run_mutation,
                }
                if github_url and github_url.strip():
                    payload["github_url"] = github_url.strip()
                else:
                    payload["source_code"] = code_input

                resp = requests.post(
                    f"{backend_url}/analyze/sync",
                    json=payload, timeout=300,
                )
                elapsed = round(time.time() - t0, 1)

                if resp.status_code == 200:
                    data = resp.json()
                    data["_elapsed"] = elapsed
                    st.session_state["last_result"] = data
                    if code_input:
                        st.session_state["code_input"] = code_input
                    st.rerun()
                else:
                    st.error(f"Backend error {resp.status_code}: {resp.text[:400]}")
            except requests.exceptions.Timeout:
                st.error("Timed out. Mutation testing can take 3–5 min — increase timeout or disable it.")
            except Exception as e:
                st.error(f"Request failed: {e}")

# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
if "last_result" in st.session_state:
    data = st.session_state["last_result"]

    if data.get("status") == "failed":
        st.error(f"Pipeline failed: {data.get('error', 'unknown error')}")
        st.stop()

    fn_name     = data.get("function_name", "?")
    test_count  = data.get("test_count", 0)
    mut_score   = data.get("mutation_score")
    test_cases  = data.get("test_cases") or []
    test_code   = data.get("test_code", "")
    categories  = data.get("test_categories") or []
    summary     = data.get("reasoning_summary", "")
    survived    = data.get("survived_mutants") or []
    elapsed     = data.get("_elapsed", "?")
    cache_hit   = data.get("cache_hit", False)
    complexity  = data.get("complexity")

    # ── Header row ──────────────────────────────────────────────────
    hdr_parts = [f"<b>{fn_name}()</b>"]
    if cache_hit:
        hdr_parts.append('<span class="badge badge-cache">⚡ Cache hit</span>')
    if complexity:
        rl = complexity.get("risk_level", "low")
        rlabel = complexity.get("risk_label", "")
        hdr_parts.append(f'<span class="badge badge-{rl}">CC {complexity.get("cyclomatic_complexity")} · {rlabel}</span>')

    st.markdown(
        f'<div class="sh">{" &nbsp; ".join(hdr_parts)}</div>',
        unsafe_allow_html=True,
    )

    # ── Metric cards ────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f"""<div class="mc">
          <div class="mc-label">Tests generated</div>
          <div class="mc-val" style="color:var(--accent)">{test_count}</div>
          <div class="mc-sub">{len(categories)} categories</div>
        </div>""", unsafe_allow_html=True)
    with col2:
        cat_str = " · ".join(cat.upper() for cat in categories)
        st.markdown(f"""<div class="mc">
          <div class="mc-label">Categories</div>
          <div style="font-family:var(--mono);font-size:0.75rem;color:var(--green);
            margin-top:0.4rem;line-height:1.6">{cat_str}</div>
        </div>""", unsafe_allow_html=True)
    with col3:
        if complexity:
            mi = complexity.get("maintainability_index", 0)
            mi_col = "var(--green)" if mi >= 65 else "var(--amber)" if mi >= 40 else "var(--red)"
            st.markdown(f"""<div class="mc">
              <div class="mc-label">Maintainability</div>
              <div class="mc-val" style="color:{mi_col}">{mi}</div>
              <div class="mc-sub">/ 100 (radon MI)</div>
            </div>""", unsafe_allow_html=True)
        else:
            st.markdown(f"""<div class="mc">
              <div class="mc-label">Runtime</div>
              <div class="mc-val" style="color:var(--amber)">{elapsed}s</div>
              <div class="mc-sub">end-to-end</div>
            </div>""", unsafe_allow_html=True)
    with col4:
        src = "⚡ cache" if cache_hit else f"⏱ {elapsed}s"
        st.markdown(f"""<div class="mc">
          <div class="mc-label">Runtime</div>
          <div class="mc-val" style="color:var(--muted);font-size:1.2rem;margin-top:0.3rem">{src}</div>
          <div class="mc-sub">{'instant replay' if cache_hit else 'LLM + pipeline'}</div>
        </div>""", unsafe_allow_html=True)

    # ── Complexity recommendation ────────────────────────────────────
    if complexity:
        rec = complexity.get("recommendation", "")
        rl  = complexity.get("risk_level", "low")
        col_map = {"low":"var(--green)","moderate":"var(--amber)","high":"var(--red)","very_high":"var(--red)"}
        border_col = col_map.get(rl, "var(--border)")
        st.markdown(f"""
        <div style="background:var(--surface);border:1px solid var(--border);
          border-left:3px solid {border_col};border-radius:8px;
          padding:0.75rem 1rem;margin:0.8rem 0;
          font-family:var(--mono);font-size:0.8rem;color:var(--muted);">
          <span style="color:{border_col};font-weight:700;">
            {complexity.get('risk_label','')}
          </span> &nbsp;·&nbsp; {rec}
        </div>""", unsafe_allow_html=True)

    # ── Mutation score ───────────────────────────────────────────────
    if mut_score is not None:
        if mut_score >= 80:
            ring_bg, ring_border, score_cls = "rgba(61,214,140,.15)","2px solid #3dd68c","var(--green)"
            verdict, vdesc = "Rigorous", "80%+ mutations killed — production-quality coverage."
        elif mut_score >= 50:
            ring_bg, ring_border, score_cls = "rgba(245,166,35,.15)","2px solid #f5a623","var(--amber)"
            verdict, vdesc = "Adequate", "Covers basics. Run the feedback loop to push past 80%."
        else:
            ring_bg, ring_border, score_cls = "rgba(224,92,92,.15)","2px solid #e05c5c","var(--red)"
            verdict, vdesc = "Weak", "Many mutations survived. The feedback loop adds targeted tests."

        st.markdown(f"""
        <div class="score-wrap">
          <div class="score-circle" style="background:{ring_bg};border:{ring_border}">
            <span style="color:{score_cls}">{mut_score:.0f}%</span>
          </div>
          <div>
            <div class="score-lbl">Mutation score</div>
            <div class="score-title" style="color:{score_cls}">{verdict}</div>
            <div class="score-desc">{vdesc}</div>
          </div>
        </div>""", unsafe_allow_html=True)

    # ── Tabs ─────────────────────────────────────────────────────────
    tab_cases, tab_code, tab_raw = st.tabs([
        f"  Test Cases ({test_count})  ",
        "  Generated Code  ",
        "  Debug / Raw  ",
    ])

    # Tab 1: Test cases
    with tab_cases:
        if summary:
            st.markdown(f"""
            <div style="background:var(--surface);border:1px solid var(--border);
              border-radius:8px;padding:0.9rem 1.1rem;margin-bottom:1rem;">
              <div class="mc-label" style="margin-bottom:0.35rem;">Agent reasoning summary</div>
              <div style="font-size:0.85rem;line-height:1.6">{summary}</div>
            </div>""", unsafe_allow_html=True)

        grouped: dict[str, list] = {}
        for tc in test_cases:
            grouped.setdefault(tc.get("category", "happy_path"), []).append(tc)

        for cat, cases in grouped.items():
            meta = CATEGORY_META.get(cat, ("?", "badge-low", "gl", "•"))
            label, badge_cls, card_cls, icon = meta
            st.markdown(
                f'<div class="sh">{icon} {label} &nbsp;·&nbsp; {len(cases)} test{"s" if len(cases)>1 else ""}</div>',
                unsafe_allow_html=True,
            )
            for tc in cases:
                inp_str   = ", ".join(f"{k}={repr(v)}" for k, v in tc.get("inputs", {}).items())
                exc       = tc.get("expected_exception")
                expected  = tc.get("expected_output")
                expect_str = f"raises {exc}" if exc else f"→ {expected}"
                st.markdown(f"""
                <div class="cc {card_cls}">
                  <div class="cc-desc">{tc.get('description','')}</div>
                  <div class="cc-inp">{inp_str} &nbsp;·&nbsp; {expect_str}</div>
                  <div class="cc-why">{tc.get('reasoning','')}</div>
                </div>""", unsafe_allow_html=True)

        if survived:
            st.markdown('<div class="sh">⚠️ Survived Mutants (fed back to agent)</div>', unsafe_allow_html=True)
            for s in survived:
                st.markdown(
                    f'<div style="font-family:var(--mono);font-size:0.74rem;color:var(--red);'
                    f'padding:0.3rem 0;border-bottom:1px solid var(--border)">{s}</div>',
                    unsafe_allow_html=True,
                )

    # Tab 2: Generated code
    with tab_code:
        if test_code:
            dl_col, _ = st.columns([1, 3])
            with dl_col:
                st.download_button(
                    "⬇  Download test file",
                    data=test_code,
                    file_name=f"test_{fn_name}.py",
                    mime="text/x-python",
                    use_container_width=True,
                )
            st.code(test_code, language="python")
        else:
            st.info("No code generated.")

    # Tab 3: Debug
    with tab_raw:
        st.markdown('<div class="sh">Raw API response</div>', unsafe_allow_html=True)
        st.json(data)

# ---------------------------------------------------------------------------
# Empty state
# ---------------------------------------------------------------------------
else:
    st.markdown("""
    <div style="text-align:center;padding:5rem 2rem;color:var(--muted)">
      <div style="font-size:3.5rem;margin-bottom:1rem">🧬</div>
      <div style="font-family:var(--mono);font-size:1rem;color:var(--text);margin-bottom:0.6rem">
        Paste a function. Click Generate.
      </div>
      <div style="font-family:var(--mono);font-size:0.78rem;line-height:1.8">
        Tree-sitter parses structure &nbsp;·&nbsp; radon scores complexity<br>
        Claude reasons about every edge case &nbsp;·&nbsp; pytest file generated<br>
        mutmut scores test quality &nbsp;·&nbsp; feedback loop improves coverage
      </div>
    </div>
    """, unsafe_allow_html=True)