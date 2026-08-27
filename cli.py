#!/usr/bin/env python3
"""
testgen CLI — Intelligent Test Generation Engine

Elite feature: this tool works WITHOUT the Streamlit UI.
Paste a file path or GitHub URL and get tests written to disk.
Integrate into CI, pre-commit hooks, or your editor.

Usage:
    python cli.py generate path/to/file.py
    python cli.py generate path/to/file.py --function my_func
    python cli.py generate https://github.com/user/repo/blob/main/utils.py
    python cli.py generate path/to/file.py --mutation --output tests/
    python cli.py analyse path/to/file.py
"""

from __future__ import annotations
import os
import sys
import time
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.syntax import Syntax
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich import print as rprint

console = Console()

sys.path.insert(0, str(Path(__file__).parent))


def _check_api_key():
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key or not key.startswith("sk-ant-"):
        console.print("[red]✗[/red] ANTHROPIC_API_KEY not set or invalid.")
        console.print("  Run: [bold]export ANTHROPIC_API_KEY=sk-ant-...[/bold]")
        sys.exit(1)


@click.group()
@click.version_option("0.1.0", prog_name="testgen")
def cli():
    """🧬 Intelligent Test Generation Engine"""
    pass


# ---------------------------------------------------------------------------
# generate command
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("source", metavar="FILE_OR_URL")
@click.option("--function", "-f", default=None, help="Target function name (auto-detect if omitted)")
@click.option("--mutation", "-m", is_flag=True, default=False, help="Run mutation testing after generation")
@click.option("--output", "-o", default=None, help="Output directory for test file (default: print to stdout)")
@click.option("--no-docker", is_flag=True, default=False, help="Skip Docker sandbox (dev mode)")
def generate(source, function, mutation, output, no_docker):
    """
    Generate tests for a Python file or GitHub URL.

    Examples:\n
        testgen generate myfile.py\n
        testgen generate myfile.py --function calculate_discount\n
        testgen generate https://github.com/user/repo/blob/main/utils.py\n
        testgen generate myfile.py --mutation --output tests/
    """
    _check_api_key()

    from backend.parser.github_fetcher import GitHubFetcher
    from backend.parser.complexity import ComplexityAnalyser
    from backend.pipeline import Pipeline

    console.print()
    console.print(Panel.fit(
        "[bold blue]🧬 TestGen Engine[/bold blue]",
        subtitle="[dim]Intelligent Test Generation[/dim]"
    ))
    console.print()

    # --- Fetch source ---
    with console.status("[bold]Loading source...[/bold]"):
        if GitHubFetcher.is_github_url(source):
            fetcher = GitHubFetcher()
            fetch_result = fetcher.fetch(source)
            if not fetch_result.success:
                console.print(f"[red]✗ GitHub fetch failed:[/red] {fetch_result.error}")
                sys.exit(1)
            source_code = fetch_result.source_code
            module_path = fetch_result.file_path
            console.print(f"[green]✓[/green] Fetched from GitHub: [dim]{fetch_result.url}[/dim]")
        else:
            path = Path(source)
            if not path.exists():
                console.print(f"[red]✗ File not found:[/red] {source}")
                sys.exit(1)
            if path.suffix != ".py":
                console.print(f"[red]✗ Not a Python file:[/red] {source}")
                sys.exit(1)
            source_code = path.read_text()
            module_path = str(path)
            console.print(f"[green]✓[/green] Loaded: [dim]{path}[/dim]")

    # --- Complexity analysis ---
    analyser = ComplexityAnalyser()
    complexity_reports = analyser.analyse_all(source_code)

    if complexity_reports:
        table = Table(title="Function Complexity", show_header=True, header_style="bold dim")
        table.add_column("Function", style="cyan")
        table.add_column("CC", justify="center")
        table.add_column("Risk", justify="center")
        table.add_column("MI", justify="center")

        colour_map = {"low": "green", "moderate": "yellow", "high": "red", "very_high": "bold red"}
        for name, r in sorted(complexity_reports.items()):
            c = colour_map.get(r.risk_level, "white")
            table.add_row(
                name,
                str(r.cyclomatic_complexity),
                f"[{c}]{r.risk_label}[/{c}]",
                str(r.maintainability_index),
            )
        console.print(table)
        console.print()

    # --- Run pipeline ---
    stages = [
        "Parsing AST + call graph",
        "Agent reasoning (LLM call 1/2)",
        "Generating pytest code (LLM call 2/2)",
        "Post-processing test file",
    ]
    if mutation:
        stages.append("Running mutation testing")
        stages.append("Feedback loop (if score < 80%)")

    pipeline = Pipeline(
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
        use_docker=not no_docker,
        max_feedback_loops=1,
    )

    t0 = time.time()

    # Run pipeline first, then show progress animation
    result = pipeline.run_from_source(
        source_code=source_code,
        target_function=function,
        run_mutation=mutation,
        module_path=module_path,
    )

    elapsed = round(time.time() - t0, 1)

    # Animate progress bar over completed stages (visual feedback only)
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Pipeline complete", total=len(stages))
        for i, stage in enumerate(stages):
            progress.update(task, description=f"[green]✓[/green] {stage}", completed=i + 1)
            time.sleep(0.15)

    if result.status == "failed":
        console.print(f"[red]✗ Pipeline failed:[/red] {result.error}")
        sys.exit(1)

    if not result.function_info or not result.generated_test or not result.agent_result:
        console.print("[red]✗ Pipeline returned incomplete result.[/red]")
        sys.exit(1)

    # --- Display results ---
    fn = result.function_info.name
    test_count = result.generated_test.test_count
    categories = sorted({tc.category.value for tc in result.agent_result.test_cases})

    console.print(Panel(
        f"[bold green]✓ Generated {test_count} tests[/bold green] for [cyan]{fn}()[/cyan]\n"
        f"  Categories: [dim]{', '.join(categories)}[/dim]\n"
        f"  Runtime: [dim]{elapsed}s[/dim]",
        title="Results",
    ))

    if result.mutation_report:
        score = result.mutation_report.mutation_score
        colour = "green" if score >= 80 else "yellow" if score >= 50 else "red"
        console.print(
            f"  Mutation score: [{colour}]{score:.1f}%[/{colour}] "
            f"({result.mutation_report.killed}/{result.mutation_report.total_mutants} killed)"
        )

    # Agent reasoning summary
    if result.agent_result.agent_reasoning_summary:
        console.print()
        console.print(f"[dim italic]{result.agent_result.agent_reasoning_summary}[/dim italic]")

    # --- Output ---
    test_code = result.generated_test.test_code

    if output:
        out_dir = Path(output)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"test_{fn}.py"
        out_file.write_text(test_code)
        console.print(f"\n[green]✓[/green] Test file written to: [bold]{out_file}[/bold]")
    else:
        console.print()
        console.print(Syntax(test_code, "python", theme="monokai", line_numbers=True))


# ---------------------------------------------------------------------------
# analyse command
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("source", metavar="FILE_OR_URL")
def analyse(source):
    """
    Analyse complexity of all functions in a Python file.
    No API calls — purely static analysis.
    """
    from backend.parser.github_fetcher import GitHubFetcher
    from backend.parser.ast_parser import ASTParser
    from backend.parser.complexity import ComplexityAnalyser

    with console.status("Analysing..."):
        if GitHubFetcher.is_github_url(source):
            fetcher = GitHubFetcher()
            r = fetcher.fetch(source)
            if not r.success:
                console.print(f"[red]✗[/red] {r.error}")
                sys.exit(1)
            source_code = r.source_code
        else:
            path = Path(source)
            if not path.exists():
                console.print(f"[red]✗ File not found:[/red] {source}")
                sys.exit(1)
            source_code = path.read_text()

    parser = ASTParser()
    parse_result = parser.parse_source(source_code)
    analyser = ComplexityAnalyser()
    reports = analyser.analyse_all(source_code)

    if not reports:
        console.print("[yellow]No functions found.[/yellow]")
        return

    table = Table(title=f"Complexity Report — {source}", show_header=True, header_style="bold")
    table.add_column("Function", style="cyan", no_wrap=True)
    table.add_column("Lines", justify="right")
    table.add_column("CC", justify="center")
    table.add_column("Risk", justify="center")
    table.add_column("MI", justify="right")
    table.add_column("Recommendation", style="dim")

    colour_map = {"low": "green", "moderate": "yellow", "high": "red", "very_high": "bold red"}

    fn_map = {f.name: f for f in parse_result.functions}
    for name, r in sorted(reports.items()):
        fn = fn_map.get(name)
        lines = f"{fn.start_line}–{fn.end_line}" if fn else "?"
        c = colour_map.get(r.risk_level, "white")
        table.add_row(
            name, lines,
            str(r.cyclomatic_complexity),
            f"[{c}]{r.risk_label}[/{c}]",
            str(r.maintainability_index),
            r.recommendation,
        )

    console.print(table)


# ---------------------------------------------------------------------------
# cache commands
# ---------------------------------------------------------------------------

@cli.group()
def cache():
    """Manage the result cache."""
    pass


@cache.command("stats")
def cache_stats():
    """Show cache statistics."""
    from backend.cache import ResultCache
    stats = ResultCache().stats()
    console.print(f"Cached results: [bold]{stats.get('size', 0)}[/bold]")
    console.print(f"Cache directory: [dim]{stats.get('dir')}[/dim]")
    console.print(f"TTL: [dim]{stats.get('ttl_hours')}h[/dim]")


@cache.command("clear")
def cache_clear():
    """Clear all cached results."""
    from backend.cache import ResultCache
    n = ResultCache().clear()
    console.print(f"[green]✓[/green] Cleared {n} cached results.")


if __name__ == "__main__":
    cli()