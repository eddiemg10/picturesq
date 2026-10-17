from pathlib import Path

from picturesq.hardware import _linux, detect, parse_cpu_list, parse_size


def test_parse_cpu_list() -> None:
    assert parse_cpu_list("0-3,8,10-11") == {0, 1, 2, 3, 8, 10, 11}
    assert parse_cpu_list("5") == {5}


def test_parse_size() -> None:
    assert parse_size("32K") == 32 * 1024
    assert parse_size("6144K") == 6 * 1024 * 1024
    assert parse_size("2M") == 2 * 1024 * 1024
    assert parse_size("512") == 512


def _fake_sysfs(root: Path) -> None:
    """4 cores x 2 hyperthreads (CPU n and n + 4 share a core), private 256K L2, shared 6M L3."""
    for cpu in range(8):
        topology = root / f"cpu{cpu}" / "topology"
        topology.mkdir(parents=True)
        (topology / "physical_package_id").write_text("0\n")
        (topology / "core_id").write_text(f"{cpu % 4}\n")
        caches = [("1", "Data", "32K"), ("1", "Instruction", "32K"), ("2", "Unified", "256K")]
        caches.append(("3", "Unified", "6144K"))
        for index, (level, kind, size) in enumerate(caches):
            folder = root / f"cpu{cpu}" / "cache" / f"index{index}"
            folder.mkdir(parents=True)
            (folder / "level").write_text(level)
            (folder / "type").write_text(kind)
            (folder / "size").write_text(size)
            shared = "0-7" if level == "3" else f"{cpu % 4},{cpu % 4 + 4}"
            (folder / "shared_cpu_list").write_text(shared)


def test_linux_counts_physical_cores_and_splits_the_last_cache(tmp_path: Path) -> None:
    _fake_sysfs(tmp_path)
    physical, cache_per_core = _linux(tmp_path, allowed=set(range(8)))
    assert physical == 4
    assert cache_per_core == 6 * 1024 * 1024 // 4  # the L3, shared by all four cores


def test_linux_respects_affinity(tmp_path: Path) -> None:
    _fake_sysfs(tmp_path)
    physical, _ = _linux(tmp_path, allowed={0, 4, 1})  # cores 0 (both threads) and 1
    assert physical == 2


def test_detect_on_this_machine_is_plausible() -> None:
    """Runs every OS reader in CI (Linux and Windows)."""
    hardware = detect()
    assert hardware.logical_cpus >= 1
    if hardware.physical_cores is not None:
        assert 1 <= hardware.physical_cores <= hardware.logical_cpus
    if hardware.cache_per_core is not None:
        assert 16 * 1024 <= hardware.cache_per_core <= 1024**3
