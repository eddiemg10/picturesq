from __future__ import annotations

from pathlib import Path
from typing import get_args

import pytest

from picturesq.config.project import DecodeConfig
from picturesq.decode import DecodeError, decode_original
from picturesq.decode.raw import DEMOSAIC_ALGORITHMS, HIGHLIGHT_MODES


def test_demosaic_table_covers_every_config_value() -> None:
    literal = DecodeConfig.model_fields["demosaic"].annotation
    assert set(DEMOSAIC_ALGORITHMS) == set(get_args(literal))


def test_highlight_table_covers_every_config_value() -> None:
    literal = DecodeConfig.model_fields["highlight_mode"].annotation
    assert set(HIGHLIGHT_MODES) == set(get_args(literal))


def test_non_raw_file_raises_decode_error(tmp_path: Path) -> None:
    junk = tmp_path / "junk.dng"
    junk.write_bytes(b"not a raw file" * 100)
    with pytest.raises(DecodeError):
        decode_original(junk, DecodeConfig())


def test_missing_file_raises_decode_error(tmp_path: Path) -> None:
    with pytest.raises(DecodeError):
        decode_original(tmp_path / "missing.raf", DecodeConfig())
