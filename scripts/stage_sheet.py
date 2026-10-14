"""Render a stage sheet for a CC0 sample, and optionally publish it to a PR description.

Panels: the camera's embedded JPEG, each scene-linear pipeline stage seen through the display
transform, the export, and the export with clipped pixels marked. Only samples listed in
reference/samples.json are accepted, so private photos can never be published.

Usage:
    uv run python scripts/stage_sheet.py [--sample dji-fc4382.dng] [--out PATH]
    uv run python scripts/stage_sheet.py --pr N     # also push to pr-previews and edit PR N
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np
import rawpy
from numpy.typing import NDArray
from PIL import Image, ImageOps

from picturesq import __version__
from picturesq.config import OutputConfig, ProjectConfig
from picturesq.decode import decode_original, read_baseline_exposure
from picturesq.export import resize_to_long_edge
from picturesq.pipeline.export import SCENE_STAGES, render_output
from picturesq.preview.stage_sheet import (
    Panel,
    compose_sheet,
    mark_clipped,
    panel_stats,
    preview_section,
    replace_section,
    stats_table,
    validate_sample_name,
)

ROOT = Path(__file__).resolve().parent.parent
PANEL_WIDTH = 500
WORK_LONG_EDGE = 800
BRANCH = "pr-previews"
BRANCH_README = (
    "Images for PR descriptions (stage sheets). CC0 samples only. This branch is never merged.\n"
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(*cmd: str, cwd: Path = ROOT) -> str:
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def camera_jpeg(path: Path) -> NDArray[np.uint8] | None:
    """The JPEG (or bitmap) embedded in the original, upright, or None if there is none."""
    try:
        with rawpy.imread(str(path)) as raw:
            thumb = raw.extract_thumb()
    except (rawpy.LibRawNoThumbnailError, rawpy.LibRawUnsupportedThumbnailError):
        return None
    if thumb.format == rawpy.ThumbFormat.JPEG:
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(thumb.data)))  # EXIF orientation
        return np.asarray(image.convert("RGB"), dtype=np.uint8)
    if thumb.format == rawpy.ThumbFormat.BITMAP:
        return np.asarray(thumb.data, dtype=np.uint8)
    return None


def build_panels(sample: Path, config: ProjectConfig) -> tuple[list[Panel], float, float]:
    """Render every panel with the production path. Returns (panels, baseline EV, decode s)."""
    started = time.perf_counter()
    full = decode_original(sample, config.decode)
    decode_seconds = time.perf_counter() - started
    image = resize_to_long_edge(full, WORK_LONG_EDGE)  # in scene-linear, before viewing
    view = OutputConfig(long_edge=PANEL_WIDTH)

    jpeg = camera_jpeg(sample)
    if jpeg is None:
        jpeg = np.full((PANEL_WIDTH * 3 // 4, PANEL_WIDTH, 3), 128, dtype=np.uint8)
        panels = [Panel("camera JPEG: no embedded JPEG", jpeg)]
    else:
        panels = [Panel("camera JPEG", jpeg)]

    panels.append(Panel("decode (via display transform)", render_output(image, view)))
    staged = image
    for name, stage in SCENE_STAGES:
        staged = stage(staged, config)
        panels.append(Panel(f"{name} (via display transform)", render_output(staged, view)))

    export = render_output(full, config.export.outputs["web"])  # the real web output
    del full
    panels.append(Panel("export (web)", export))
    panels.append(Panel("clipping (magenta)", mark_clipped(export)))
    return panels, read_baseline_exposure(sample), decode_seconds


def publish(sheet_path: Path, number: int, sha: str, section_for: Callable[[str], str]) -> None:
    """Push the sheet to the pr-previews branch and update the PR body."""
    repo = run("gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner")
    url = f"https://raw.githubusercontent.com/{repo}/{BRANCH}/pr/{number}/{sha}.jpg"
    with tempfile.TemporaryDirectory() as tmp:
        worktree = Path(tmp) / "wt"
        have_remote = bool(run("git", "ls-remote", "--heads", "origin", BRANCH))
        try:
            if have_remote:
                run("git", "fetch", "origin", BRANCH)
                run("git", "worktree", "add", "--detach", str(worktree), f"origin/{BRANCH}")
                run("git", "checkout", "-B", BRANCH, cwd=worktree)
            else:
                run("git", "worktree", "add", "--detach", str(worktree))
                run("git", "checkout", "--orphan", BRANCH, cwd=worktree)
                run("git", "rm", "-rf", "--quiet", ".", cwd=worktree)
                (worktree / "README.md").write_text(BRANCH_README)
                run("git", "add", "README.md", cwd=worktree)
            target = worktree / "pr" / str(number) / f"{sha}.jpg"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(sheet_path, target)
            run("git", "add", str(target.relative_to(worktree)), cwd=worktree)
            message = f"chore(previews): stage sheet for #{number} at {sha}"
            run("git", "commit", "-m", message, cwd=worktree)
            run("git", "push", "origin", BRANCH, cwd=worktree)
        finally:
            run("git", "worktree", "remove", "--force", str(worktree))
            run("git", "branch", "-D", BRANCH)
    body = run("gh", "pr", "view", str(number), "--json", "body", "--jq", ".body")
    new_body = replace_section(body, section_for(url))
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(new_body)
    try:
        run("gh", "pr", "edit", str(number), "--body-file", f.name)
    finally:
        os.unlink(f.name)
    print(f"updated PR #{number}: {url}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--sample", default="dji-fc4382.dng", help="name from reference/samples.json"
    )
    parser.add_argument("--out", type=Path, default=None, help="where to write the sheet (JPEG)")
    parser.add_argument("--pr", type=int, default=None, help="publish to this PR's description")
    args = parser.parse_args()

    manifest = json.loads((ROOT / "reference" / "samples.json").read_text())
    entries = {s["name"]: s for s in manifest["samples"]}
    try:
        name = validate_sample_name(args.sample, list(entries))
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    samples_dir = Path(os.environ.get("PICTURESQ_SAMPLES", ROOT / "reference" / "samples"))
    sample = samples_dir / name
    if not sample.is_file():
        print(f"error: {sample} not found; run scripts/fetch_samples.py", file=sys.stderr)
        return 1
    if sha256(sample) != entries[name]["sha256"]:
        print(f"error: {sample} does not match the checksum in samples.json", file=sys.stderr)
        return 1

    config = ProjectConfig()
    panels, baseline, decode_seconds = build_panels(sample, config)
    sha = run("git", "rev-parse", "--short", "HEAD")
    title = f"{name} · picturesq {__version__} · {sha} · default config"
    sheet = compose_sheet(title, panels, (PANEL_WIDTH, PANEL_WIDTH * 3 // 4))
    out = args.out or Path(tempfile.gettempdir()) / "picturesq-stage-sheet" / f"{name}-{sha}.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=88)
    print(f"wrote {out} ({sheet.width}x{sheet.height})\n")

    table = stats_table([panel_stats(p) for p in panels], baseline, decode_seconds)
    print(table)
    caption = (
        f"{name} (CC0) · {sha} · panels: "
        + ", ".join(p.label for p in panels)
        + "; scene-linear stages are viewed through the current display transform; "
        "magenta = clipped"
    )
    if args.pr is not None:
        publish(out, args.pr, sha, lambda url: preview_section(url, caption, table))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
