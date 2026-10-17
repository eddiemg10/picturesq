"""`picturesq export` and `picturesq run`: RAW folder in, JPEGs out."""

import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import typer

from picturesq.cli.config import EXIT_ERROR, EXIT_INVALID, fail, project_config
from picturesq.decode import DecodeError, find_originals, read_pixel_count
from picturesq.hardware import available_memory, detect
from picturesq.pipeline.budget import photo_peak_bytes
from picturesq.pipeline.export import (
    EXPORTS_DIRNAME,
    ExportResult,
    PhotoResult,
    StemCollisionError,
    export_originals,
)
from picturesq.pipeline.workers import (
    WorkerPlan,
    default_memory_budget,
    format_bytes,
    plan_workers,
)


@dataclass(frozen=True)
class MachineOptions:
    """The global CLI options that size the work; None means automatic."""

    threads: int | None = None
    workers: int | None = None
    memory_budget: int | None = None


def _pixels(original: Path) -> int:
    try:
        return read_pixel_count(original)
    except DecodeError:
        return 0  # it fails again when exported, and is reported then


def worker_plan(originals: Sequence[Path], machine: MachineOptions) -> WorkerPlan:
    """How to export ``originals`` on this machine (pixel counts read from the headers)."""
    hardware = detect()
    budget = machine.memory_budget
    if budget is None:
        budget = default_memory_budget(available_memory())
    return plan_workers(
        [_pixels(original) for original in originals],
        cores=hardware.physical_cores or hardware.logical_cpus,
        memory_budget=budget,
        max_photos=machine.workers,
        threads=machine.threads,
    )


def _photo_line(photo: PhotoResult) -> str:
    if photo.error is not None:
        return f"{photo.name}: FAILED ({photo.error})"
    outputs = ", ".join(photo.outputs)
    return f"{photo.name}: {outputs} ({photo.seconds:.1f}s)"


def _json_document(result: ExportResult, plan: WorkerPlan) -> str:
    document = {
        "photos": [
            {
                "photo": photo.name,
                "outputs": {name: str(path) for name, path in photo.outputs.items()},
                "error": photo.error,
                "seconds": round(photo.seconds, 3),
            }
            for photo in result.photos
        ],
        "summary": {
            "photos": len(result.photos),
            "failed": result.failed,
            "seconds": round(result.seconds, 3),
            "workers": plan.workers,
        },
    }
    return json.dumps(document, indent=2)


def render_project(
    project_arg: str,
    *,
    create_config: bool,
    output_names: list[str] | None,
    out: Path | None,
    as_json: bool,
    machine: MachineOptions | None = None,
) -> None:
    """Shared body of `export` and `run`. Progress lines go to stdout; none in JSON mode."""
    project = Path(project_arg)
    if not project.is_dir():
        raise fail(f"{project} is not a folder", EXIT_INVALID)
    config = project_config(project, create=create_config)
    if output_names:
        unknown = [name for name in output_names if name not in config.export.outputs]
        if unknown:
            defined = ", ".join(sorted(config.export.outputs))
            raise fail(f"unknown output(s) {unknown}; defined: {defined}", EXIT_INVALID)
    originals = find_originals(project)
    if not originals:
        raise fail(f"no originals found in {project}", EXIT_ERROR)

    def report(photo: PhotoResult) -> None:
        if not as_json:
            typer.echo(_photo_line(photo))

    plan = worker_plan(originals, machine or MachineOptions())
    if plan.over_budget:
        assert plan.memory_budget is not None
        largest = photo_peak_bytes(max(plan.pixels))
        typer.echo(
            f"warning: the largest photo needs about {format_bytes(largest)}, over the "
            f"memory budget of {format_bytes(plan.memory_budget)}; exporting it anyway, "
            "alone (raise --memory-budget, or close other programs if the system swaps)",
            err=True,
        )

    exports_dir = out if out is not None else project / EXPORTS_DIRNAME
    try:
        result = export_originals(
            originals,
            config,
            exports_dir,
            outputs=output_names or None,
            on_photo=report,
            plan=plan,
        )
    except StemCollisionError as error:
        raise fail(str(error), EXIT_ERROR) from None

    if as_json:
        sys.stdout.write(_json_document(result, plan) + "\n")
    else:
        typer.echo(
            f"{len(result.photos)} photo(s), {result.failed} failed, {result.seconds:.1f}s "
            f"on {plan.describe()}"
        )
    if result.failed:
        raise typer.Exit(code=EXIT_ERROR)
