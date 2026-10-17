"""Proxies of real CC0 samples match the full decode they stand in for."""

from pathlib import Path

import numpy as np
import pytest

from picturesq.config import DecodeConfig
from picturesq.decode import decode_original
from picturesq.export import resize_to_long_edge
from picturesq.pipeline.proxy import load_proxy

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "name", ["dji-fc4382.dng", "pentax-q7.dng", "sony-ilme-fx3.arw", "fujifilm-xq1.raf"]
)
def test_proxy_matches_the_full_decode(samples_dir: Path, tmp_path: Path, name: str) -> None:
    original = samples_dir / name
    if not original.exists():
        pytest.skip(f"{name} not found in {samples_dir}")
    config = DecodeConfig()
    proxy = load_proxy(original, config, tmp_path).image
    full = decode_original(original, config)
    height, width = full.shape[:2]
    # Same frame: the half-size decode honours the default crop and orientation.
    assert max(proxy.shape[:2]) == min(config.proxy_long_edge, max(height, width) // 2)
    assert abs(proxy.shape[1] / proxy.shape[0] - width / height) < 0.01
    reference = resize_to_long_edge(full, max(proxy.shape[:2]))
    assert reference.shape == proxy.shape
    # Same exposure and colour (per channel, in stops), not pixel-identical: the half-size
    # path skips demosaicing.
    for channel in range(3):
        ratio = proxy[..., channel].mean() / reference[..., channel].mean()
        assert abs(np.log2(ratio)) < 0.05, (channel, ratio)
    assert load_proxy(original, config, tmp_path).cached
