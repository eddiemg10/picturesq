"""`picturesq ui`: serve the local web UI for one project."""

import threading
import webbrowser
from pathlib import Path

import typer

from picturesq.cli.config import EXIT_ERROR, EXIT_INVALID, fail
from picturesq.config import ConfigError, LookFileError


def serve_project(project_arg: str, *, host: str, port: int, open_browser: bool) -> None:
    """Body of `picturesq ui`: open the project, start the server, open the browser."""
    import uvicorn

    from picturesq.ui.app import create_app
    from picturesq.ui.session import Session

    project = Path(project_arg)
    if not project.is_dir():
        raise fail(f"{project} is not a folder", EXIT_INVALID)
    try:
        session = Session.open(project)
    except ConfigError as error:
        raise fail(str(error), EXIT_INVALID) from None
    except LookFileError as error:
        raise fail(str(error), EXIT_ERROR) from None
    if not session.names:
        raise fail(f"no originals found in {project}", EXIT_ERROR)
    url = f"http://{host}:{port}/"
    typer.echo(f"picturesq ui: {len(session.names)} photo(s) in {project} at {url} (Ctrl+C stops)")
    if open_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run(create_app(session), host=host, port=port, log_level="warning")
