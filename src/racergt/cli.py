from __future__ import annotations

from pathlib import Path

import pandas as pd
import typer
from rich.console import Console
from rich.table import Table

from .audit import audit_raw_batch
from .config import RacerGTConfig
from .design import write_protocol_bundle
from .factor import IndefiniteCovarianceError, fit_error_corrected_factors
from .io import read_table, write_table
from .pipeline import RacerGTPipeline
from .report import generate_diagnostic_report
from .simulation import SimulationSettings, simulate_racergt_data

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="RACER-GT: reproducible construction and reliability analysis of long-horizon Google Trends indices.",
)
console = Console()


@app.command("design")
def design_command(
    config_path: Path = typer.Argument(..., exists=True, readable=True),
    output_dir: Path = typer.Option(Path("protocol_bundle"), "--out", "-o"),
    anchor_date: str | None = typer.Option(None, help="Calendar date corresponding to Day 0."),
) -> None:
    """Create the locked protocol, balanced schedule, and fixed chunk windows."""
    config = RacerGTConfig.load_yaml(config_path)
    paths = write_protocol_bundle(config, output_dir, anchor_date=anchor_date)
    console.print(f"[bold green]Protocol hash:[/bold green] {config.protocol_hash()}")
    for name, path in paths.items():
        console.print(f"{name}: {path}")


@app.command("audit")
def audit_command(
    config_path: Path = typer.Argument(..., exists=True, readable=True),
    raw_path: Path = typer.Argument(..., exists=True, readable=True),
    output_path: Path = typer.Option(Path("audit.json"), "--out", "-o"),
) -> None:
    """Audit raw chunk data against a locked protocol."""
    config = RacerGTConfig.load_yaml(config_path)
    raw = read_table(raw_path)
    result = audit_raw_batch(raw, config)
    result.save_json(output_path)
    table = Table("Severity", "Code", "Message", "Rows")
    for issue in result.issues:
        table.add_row(issue.severity, issue.code, issue.message, str(issue.rows or ""))
    console.print(table)
    console.print(f"Audit passed: [bold]{result.passed}[/bold]")
    if not result.passed:
        raise typer.Exit(code=2)


@app.command("run")
def run_command(
    config_path: Path = typer.Argument(..., exists=True, readable=True),
    raw_path: Path = typer.Argument(..., exists=True, readable=True),
    output_dir: Path = typer.Option(Path("racergt_results"), "--out", "-o"),
    benchmark_path: Path | None = typer.Option(None, "--benchmark", "-b"),
    make_report: bool = typer.Option(True, "--report/--no-report"),
) -> None:
    """Run the complete RACER-GT measurement pipeline."""
    config = RacerGTConfig.load_yaml(config_path)
    raw = read_table(raw_path)
    benchmark = read_table(benchmark_path) if benchmark_path else None
    result = RacerGTPipeline(config).fit(raw, benchmark=benchmark)
    paths = result.save(output_dir)
    if make_report:
        report_path = generate_diagnostic_report(result, output_dir / "report")
        paths["report"] = report_path
    console.print(f"Decision: [bold]{result.decision.status}[/bold]")
    for name, path in paths.items():
        console.print(f"{name}: {path}")
    if result.decision.status == "FAIL":
        raise typer.Exit(code=3)


@app.command("simulate")
def simulate_command(
    config_path: Path = typer.Argument(..., exists=True, readable=True),
    output_dir: Path = typer.Option(Path("racergt_simulation"), "--out", "-o"),
    seed: int = typer.Option(20260727),
    run_pipeline: bool = typer.Option(True, "--run/--no-run"),
) -> None:
    """Generate a controlled GT-like dataset and optionally run the full pipeline."""
    output_dir.mkdir(parents=True, exist_ok=True)
    config = RacerGTConfig.load_yaml(config_path)
    simulated = simulate_racergt_data(config, SimulationSettings(random_seed=seed))
    raw_path = write_table(simulated.raw_chunks, output_dir / "simulated_raw_chunks.csv")
    benchmark_path = write_table(simulated.benchmark, output_dir / "simulated_benchmark.csv")
    truth_path = write_table(simulated.truth, output_dir / "simulated_truth.csv")
    schedule_path = write_table(simulated.schedule, output_dir / "simulated_schedule.csv")
    console.print(f"raw: {raw_path}\nbenchmark: {benchmark_path}\ntruth: {truth_path}\nschedule: {schedule_path}")
    if run_pipeline:
        result = RacerGTPipeline(config).fit(simulated.raw_chunks, simulated.benchmark)
        result_dir = output_dir / "results"
        result.save(result_dir)
        generate_diagnostic_report(result, result_dir / "report")
        console.print(f"Simulation decision: [bold]{result.decision.status}[/bold]")


@app.command("factor")
def factor_command(
    manifest_path: Path = typer.Argument(..., exists=True, readable=True),
    output_dir: Path = typer.Option(Path("racergt_factor"), "--out", "-o"),
    n_factors: int | None = typer.Option(None, "--factors", "-k"),
    standardize: bool = typer.Option(True, "--standardize/--no-standardize"),
    max_zero_share: float = typer.Option(0.50, "--max-zero-share"),
    allow_indefinite: bool = typer.Option(False, "--allow-indefinite"),
) -> None:
    """Fit an error-corrected factor model across per-series consensus outputs.

    The manifest is a CSV with columns series_id and path. Each path points at a
    consensus series carrying value and standard_error, and is resolved relative to
    the manifest so the bundle stays portable. Exits 4 when the error-corrected
    covariance is not positive semidefinite, which says measurement error explains
    more of the covariance than the factors do.
    """
    manifest = read_table(manifest_path)
    missing = {"series_id", "path"}.difference(manifest.columns)
    if missing:
        console.print(f"[bold red]Manifest is missing columns:[/bold red] {sorted(missing)}")
        raise typer.Exit(code=2)

    frames = []
    for row in manifest.itertuples():
        series_path = Path(str(row.path))
        if not series_path.is_absolute():
            series_path = manifest_path.parent / series_path
        series = read_table(series_path)
        series["series_id"] = str(row.series_id)
        frames.append(series)
    combined = pd.concat(frames, ignore_index=True)

    try:
        result = fit_error_corrected_factors(
            combined,
            n_factors=n_factors,
            standardize=standardize,
            max_zero_share=max_zero_share,
            allow_indefinite=allow_indefinite,
        )
    except IndefiniteCovarianceError as error:
        console.print(f"[bold red]Indefinite corrected covariance:[/bold red] {error}")
        raise typer.Exit(code=4) from error

    paths = result.save(output_dir)
    diagnostics = result.diagnostics
    table = Table("Diagnostic", "Value")
    table.add_row("factors retained", str(diagnostics["n_factors"]))
    table.add_row("series used", f"{diagnostics['n_series_used']}/{diagnostics['n_series_requested']}")
    table.add_row("measurement error share", f"{diagnostics['measurement_error_share']:.4f}")
    table.add_row("corrected covariance is PSD", str(diagnostics["corrected_covariance_is_psd"]))
    table.add_row("min eigenvalue (corrected)", f"{diagnostics['min_eigenvalue_corrected']:.6g}")
    table.add_row("PC1 weekday F", f"{diagnostics['pc1_weekday_f_statistic']:.3f}")
    table.add_row("PC1 lag-7 autocorrelation", f"{diagnostics['pc1_autocorr_lag7']:.3f}")
    table.add_row("Omega source", str(diagnostics["omega_source"]))
    table.add_row("Omega is a daily variance", str(diagnostics["omega_is_daily_variance"]))
    console.print(table)
    # PC1 is whatever varies most in common, and GT series share large calendar
    # effects, so a high weekday F is reported at the same prominence as the fit.
    if diagnostics["pc1_weekday_f_statistic"] > 10.0:
        console.print(
            "[bold yellow]PC1 tracks the day of week.[/bold yellow] "
            "Treating it as the construct needs an argument this diagnostic does not supply."
        )
    for name, path in paths.items():
        console.print(f"{name}: {path}")


@app.command("export-stata")
def export_stata_command(
    csv_path: Path = typer.Argument(..., exists=True, readable=True),
    dta_path: Path = typer.Argument(...),
) -> None:
    """Export a RACER-GT CSV table to Stata 118 format."""
    data = read_table(csv_path)
    write_table(data, dta_path)
    console.print(f"Wrote {dta_path}")


if __name__ == "__main__":
    app()
