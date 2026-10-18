"""The proxy cache: a small scene-linear copy of each photo for previews and the UI.

A proxy is a half-size decode (no demosaic: each 2x2 sensor block becomes one pixel, ~4x
faster) downscaled to ``decode.proxy_long_edge`` and stored as float16 ``.npy`` in
``<project>/.picturesq/proxies/<stem>.<key>.npy``. Stages 2-3 run on it like on a full
decode; only exports go back to the original.

The ``key`` hashes the original's bytes, the decode config, the proxy format and the
picturesq version, so a stale proxy can't be read: any change gives a new key and a new
file, and the old one is deleted when the new one is written.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np
from numpy.typing import NDArray

from picturesq import __version__
from picturesq.atomic import atomic_write
from picturesq.config import DecodeConfig
from picturesq.decode import DecodeError, decode_original
from picturesq.export import resize_to_long_edge, sha256_file

CACHE_DIRNAME: Final = ".picturesq"
PROXIES_DIRNAME: Final = "proxies"
PROXY_FORMAT: Final = 1
"""Bump when the proxy's contents change in a way the decode config doesn't capture."""
_KEY_LENGTH: Final = 16


def proxy_key(original_sha256: str, decode: DecodeConfig, *, version: str = __version__) -> str:
    """Cache key of the proxy of an original with this hash, under this decode config."""
    material = json.dumps(
        {
            "format": PROXY_FORMAT,
            "version": version,
            "original": original_sha256,
            "decode": decode.model_dump(mode="json"),
        },
        sort_keys=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:_KEY_LENGTH]


def proxy_path(cache_dir: Path, original: Path, key: str) -> Path:
    """``<cache_dir>/proxies/<stem>.<key>.npy``."""
    return cache_dir / PROXIES_DIRNAME / f"{original.stem}.{key}.npy"


def _other_proxies(cache_dir: Path, original: Path, keep: Path) -> list[Path]:
    """This original's proxies under any key but ``keep``'s (stale after a change)."""
    pattern = re.compile(rf"{re.escape(original.stem)}\.[0-9a-f]{{{_KEY_LENGTH}}}\.npy")
    folder = cache_dir / PROXIES_DIRNAME
    if not folder.is_dir():
        return []
    return [p for p in folder.iterdir() if p != keep and pattern.fullmatch(p.name)]


def build_proxy(original: Path, decode: DecodeConfig) -> NDArray[np.float16]:
    """Half-size decode, downscaled (anti-ringing Lanczos, in linear) and stored as float16.

    float16 keeps ~3 significant digits from 6e-5 to 65504: plenty for scene-linear values
    that a preview quantises to 8 bits anyway, at half the size of float32.
    """
    image = decode_original(original, decode, half_size=True)
    return resize_to_long_edge(image, decode.proxy_long_edge).astype(np.float16)


def _read(path: Path) -> NDArray[np.float16] | None:
    """A cached proxy, or None if it is missing or unreadable (rebuilt by the caller)."""
    try:
        proxy = np.load(path, allow_pickle=False)
    except (OSError, ValueError, EOFError):
        return None
    if proxy.dtype != np.float16 or proxy.ndim != 3 or proxy.shape[2] != 3:
        return None
    return proxy


def _write(path: Path, proxy: NDArray[np.float16]) -> None:
    buffer = io.BytesIO()
    np.save(buffer, proxy, allow_pickle=False)
    atomic_write(path, buffer.getvalue())


@dataclass
class Proxy:
    """A photo's proxy as float32 (the working precision), and whether it came from cache."""

    image: NDArray[np.float32]
    path: Path
    cached: bool
    key: str
    """The cache key (:func:`proxy_key`): changes whenever the proxy would."""


def load_proxy(original: Path, decode: DecodeConfig, cache_dir: Path) -> Proxy:
    """The proxy of ``original``: from the cache when current, else built and cached.

    Raises DecodeError if the original can't be decoded.
    """
    key = proxy_key(sha256_file(original), decode)
    path = proxy_path(cache_dir, original, key)
    proxy = _read(path)
    cached = proxy is not None
    if proxy is None:
        proxy = build_proxy(original, decode)
        _write(path, proxy)
        for stale in _other_proxies(cache_dir, original, keep=path):
            stale.unlink(missing_ok=True)
    return Proxy(image=proxy.astype(np.float32), path=path, cached=cached, key=key)


@dataclass
class ProxyResult:
    """What happened to one photo in a ``build_proxies`` run."""

    name: str
    path: Path | None = None
    cached: bool = False
    error: str | None = None
    seconds: float = 0.0


def build_proxies(
    originals: Sequence[Path],
    decode: DecodeConfig,
    cache_dir: Path,
    *,
    on_photo: Callable[[ProxyResult], None] | None = None,
) -> list[ProxyResult]:
    """Make sure every original has a current proxy. A photo that fails is recorded and the
    run continues."""
    results: list[ProxyResult] = []
    for original in originals:
        started = time.perf_counter()
        result = ProxyResult(name=original.name)
        try:
            proxy = load_proxy(original, decode, cache_dir)
            result.path, result.cached = proxy.path, proxy.cached
            del proxy
        except (DecodeError, OSError) as error:
            result.error = str(error)
        result.seconds = time.perf_counter() - started
        results.append(result)
        if on_photo is not None:
            on_photo(result)
    return results
