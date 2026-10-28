"""The web app behind `picturesq ui`: a JSON API over a :class:`Session`, plus the page.

Routes:

- ``GET /``: the page (``templates/index.html``); ``/static/*`` its script and styles.
- ``GET /api/state``: photos, looks, the project's look and adjustments (``Session.state``).
- ``GET /api/preview/{photo}?size=thumb|large&variant=current|neutral|none|look:<key>``
  (``&draft=<json>`` for an unsaved look/adjustments while a slider moves): a JPEG.
- ``POST /api/edit``: one edit (``Session.edit``), saved to ``picturesq.yaml``.
- ``GET /api/events``: server-sent events, ``{"revision": n}`` whenever the config changes,
  from the UI or from an agent editing the file.
- ``GET /api/config``: the YAML as saved.
- ``POST /api/export`` (``{"outputs": [...]}``) and ``GET /api/export``: run
  ``picturesq export`` in a separate process and report its progress.
- ``POST /api/metadata/apply`` (``{"outputs": [...]}``): rewrite the dates in exports already
  written, as ``picturesq metadata apply``.

Binds to localhost only: there is no authentication, and the project is the user's.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import subprocess
import sys
import threading
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import (
    FileResponse,
    JSONResponse,
    PlainTextResponse,
    Response,
    StreamingResponse,
)
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from picturesq.config import ConfigError, dump_project_config
from picturesq.decode import DecodeError
from picturesq.normalise import WhiteBalanceOverrideError
from picturesq.ui.session import LONG_EDGES, EditError, Session

UI_DIR: Final = Path(__file__).parent
POLL_SECONDS: Final = 0.5
"""How often the event stream checks ``picturesq.yaml`` for edits from outside the UI."""


@dataclass
class ExportJob:
    """One `picturesq export` run started from the UI."""

    outputs: list[str]
    total: int
    done: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    running: bool = True
    exit_code: int | None = None
    started: float = field(default_factory=time.monotonic)
    finished: float | None = None

    def to_dict(self) -> dict[str, Any]:
        end = self.finished if self.finished is not None else time.monotonic()
        return {
            "outputs": self.outputs,
            "total": self.total,
            "done": len(self.done),
            "failed": self.failed,
            "running": self.running,
            "exit_code": self.exit_code,
            "seconds": round(end - self.started, 1),
            "last": self.lines[-1] if self.lines else None,
        }


def _run_export(job: ExportJob, project: Path, names: list[str]) -> None:
    command = [sys.executable, "-m", "picturesq", "export", str(project)]
    for output in job.outputs:
        command += ["--output", output]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert process.stdout is not None
    for raw in process.stdout:
        line = raw.rstrip()
        job.lines.append(line)
        name, _, rest = line.partition(": ")
        if name in names:
            (job.failed if rest.startswith("FAILED") else job.done).append(name)
    job.exit_code = process.wait()
    job.running = False
    job.finished = time.monotonic()


def create_app(session: Session) -> Starlette:
    export_job: dict[str, ExportJob] = {}

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        # Normalise every photo's thumbnail base in the background, so the strip fills fast.
        threading.Thread(target=session.warm, name="warm", daemon=True).start()
        yield

    async def index(request: Request) -> Response:
        return FileResponse(UI_DIR / "templates" / "index.html")

    async def state(request: Request) -> Response:
        try:
            await run_in_threadpool(session.reload)
        except ConfigError as error:
            return JSONResponse({"error": str(error)}, status_code=409)
        return JSONResponse(session.state())

    async def preview(request: Request) -> Response:
        name = request.path_params["photo"]
        size = request.query_params.get("size", "thumb")
        if size not in LONG_EDGES:
            return PlainTextResponse("size must be thumb, medium or large", status_code=400)
        which = request.query_params.get("variant", "current")
        draft = None
        if "draft" in request.query_params:
            try:
                draft = json.loads(request.query_params["draft"])
            except json.JSONDecodeError:
                return PlainTextResponse("draft must be JSON", status_code=400)
        if name not in session.names:
            return PlainTextResponse(f"no photo named {name!r}", status_code=404)

        def render() -> bytes:
            variant = session.variant(name, which, draft)
            return session.preview(name, size, variant)  # type: ignore[arg-type]

        try:
            data = await run_in_threadpool(render)
        except EditError as error:
            return PlainTextResponse(str(error), status_code=400)
        except (DecodeError, OSError, ValueError, WhiteBalanceOverrideError) as error:
            return PlainTextResponse(f"{name}: {error}", status_code=500)
        # The URL carries the config revision, so a cached copy is never stale.
        headers = {"Cache-Control": "private, max-age=3600"}
        return Response(data, media_type="image/jpeg", headers=headers)

    async def edit(request: Request) -> Response:
        try:
            change = await request.json()
        except json.JSONDecodeError:
            return JSONResponse({"error": "body must be JSON"}, status_code=400)
        try:
            await run_in_threadpool(session.edit, change)
        except (EditError, ConfigError) as error:
            return JSONResponse({"error": str(error)}, status_code=400)
        return JSONResponse(session.state())

    async def config(request: Request) -> Response:
        return PlainTextResponse(dump_project_config(session.config), media_type="text/yaml")

    async def events(request: Request) -> Response:
        async def stream() -> AsyncIterator[str]:
            seen = -1
            error: str | None = None
            while not await request.is_disconnected():
                try:
                    await run_in_threadpool(session.reload)
                    message = None
                except ConfigError as problem:
                    message = str(problem)
                if session.revision != seen or message != error:
                    seen, error = session.revision, message
                    payload = {"revision": seen, "error": error}
                    yield f"data: {json.dumps(payload)}\n\n"
                await asyncio.sleep(POLL_SECONDS)

        return StreamingResponse(stream(), media_type="text/event-stream")

    async def export(request: Request) -> Response:
        job = export_job.get("current")
        if request.method == "GET":
            return JSONResponse(None if job is None else job.to_dict())
        if job is not None and job.running:
            return JSONResponse({"error": "an export is already running"}, status_code=409)
        try:
            body = await request.json()
        except json.JSONDecodeError:
            body = {}
        outputs = list(body.get("outputs") or session.config.export.enabled)
        unknown = [name for name in outputs if name not in session.config.export.outputs]
        if unknown:
            return JSONResponse({"error": f"unknown outputs {unknown}"}, status_code=400)
        names = session.names
        job = ExportJob(outputs=outputs, total=len(names))
        export_job["current"] = job
        threading.Thread(
            target=_run_export, args=(job, session.project, names), daemon=True
        ).start()
        return JSONResponse(job.to_dict())

    async def apply_metadata(request: Request) -> Response:
        try:
            body = await request.json()
        except json.JSONDecodeError:
            body = {}
        outputs = list(body.get("outputs") or session.config.export.enabled)
        unknown = [name for name in outputs if name not in session.config.export.outputs]
        if unknown:
            return JSONResponse({"error": f"unknown outputs {unknown}"}, status_code=400)
        job = export_job.get("current")
        if job is not None and job.running:
            return JSONResponse(
                {"error": "an export is running; try when it ends"}, status_code=409
            )
        result = await run_in_threadpool(session.rewrite_export_dates, outputs)
        return JSONResponse(result)

    routes = [
        Route("/", index),
        Route("/api/state", state),
        Route("/api/preview/{photo}", preview),
        Route("/api/edit", edit, methods=["POST"]),
        Route("/api/config", config),
        Route("/api/events", events),
        Route("/api/export", export, methods=["GET", "POST"]),
        Route("/api/metadata/apply", apply_metadata, methods=["POST"]),
        Mount("/static", StaticFiles(directory=UI_DIR / "static"), name="static"),
    ]
    return Starlette(routes=routes, lifespan=lifespan)
