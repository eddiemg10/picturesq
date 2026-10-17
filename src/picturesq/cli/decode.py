"""`picturesq decode`: build (or refresh) the proxy cache."""

import json
import sys
import time
from pathlib import Path

import typer

from picturesq.cli.config import EXIT_ERROR, EXIT_INVALID, fail, project_config
from picturesq.decode import find_originals
from picturesq.pipeline.export import StemCollisionError, check_stems
from picturesq.pipeline.proxy import CACHE_DIRNAME, ProxyResult, build_proxies


def _photo_line(photo: ProxyResult) -> str:
    if photo.error is not None:
        return f"{photo.name}: FAILED ({photo.error})"
    state = "cached" if photo.cached else "built"
    return f"{photo.name}: {state} ({photo.seconds:.1f}s)"


def _json_document(results: list[ProxyResult], seconds: float) -> str:
    document = {
        "photos": [
            {
                "photo": photo.name,
                "proxy": None if photo.path is None else str(photo.path),
                "cached": photo.cached,
                "error": photo.error,
                "seconds": round(photo.seconds, 3),
            }
            for photo in results
        ],
        "summary": {
            "photos": len(results),
            "built": sum(1 for p in results if p.error is None and not p.cached),
            "cached": sum(1 for p in results if p.cached),
            "failed": sum(1 for p in results if p.error is not None),
            "seconds": round(seconds, 3),
        },
    }
    return json.dumps(document, indent=2)


def decode_project(project_arg: str, *, as_json: bool) -> None:
    """Body of `picturesq decode`. Progress lines go to stdout; none in JSON mode."""
    project = Path(project_arg)
    if not project.is_dir():
        raise fail(f"{project} is not a folder", EXIT_INVALID)
    config = project_config(project, create=False)
    originals = find_originals(project)
    if not originals:
        raise fail(f"no originals found in {project}", EXIT_ERROR)
    try:
        check_stems(originals)
    except StemCollisionError as error:
        raise fail(str(error), EXIT_ERROR) from None

    def report(photo: ProxyResult) -> None:
        if not as_json:
            typer.echo(_photo_line(photo))

    started = time.perf_counter()
    results = build_proxies(originals, config.decode, project / CACHE_DIRNAME, on_photo=report)
    seconds = time.perf_counter() - started
    failed = sum(1 for p in results if p.error is not None)
    if as_json:
        sys.stdout.write(_json_document(results, seconds) + "\n")
    else:
        cached = sum(1 for p in results if p.cached)
        built = len(results) - cached - failed
        typer.echo(
            f"{len(results)} photo(s): {built} built, {cached} cached, {failed} failed, "
            f"{seconds:.1f}s"
        )
    if failed:
        raise typer.Exit(code=EXIT_ERROR)
