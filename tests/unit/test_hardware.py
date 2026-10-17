from pathlib import Path

from picturesq.hardware import (
    _linux,
    available_memory,
    cgroup_available_memory,
    detect,
    linux_available_memory,
    parse_cpu_list,
    parse_meminfo,
    parse_size,
    parse_vm_stat,
)


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


def test_parse_meminfo() -> None:
    text = "MemTotal:        8054804 kB\nMemFree:         4704704 kB\nMemAvailable:    6889308 kB\n"
    assert parse_meminfo(text) == 6889308 * 1024
    assert parse_meminfo("MemTotal: 1 kB\n") is None


def _fake_cgroup(root: Path, limit: str, current: int, inactive_file: int) -> Path:
    root.mkdir()
    (root / "memory.max").write_text(f"{limit}\n")
    (root / "memory.current").write_text(f"{current}\n")
    (root / "memory.stat").write_text(f"anon 123\ninactive_file {inactive_file}\nactive_file 9\n")
    return root


def test_cgroup_limit_counts_reclaimable_file_cache(tmp_path: Path) -> None:
    cgroup = _fake_cgroup(tmp_path / "cg", str(4 << 30), current=3 << 30, inactive_file=1 << 29)
    assert cgroup_available_memory(cgroup) == (1 << 30) + (1 << 29)


def test_unlimited_or_missing_cgroup_is_unknown(tmp_path: Path) -> None:
    assert cgroup_available_memory(_fake_cgroup(tmp_path / "cg", "max", 5, 0)) is None
    assert cgroup_available_memory(tmp_path / "missing") is None


def test_linux_available_memory_is_the_smaller_of_system_and_container(tmp_path: Path) -> None:
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemAvailable:    6291456 kB\n")  # 6 GiB
    cgroup = _fake_cgroup(tmp_path / "cg", str(2 << 30), current=1 << 30, inactive_file=0)
    assert linux_available_memory(meminfo, cgroup) == 1 << 30
    assert linux_available_memory(meminfo, tmp_path / "none") == 6 << 30
    assert linux_available_memory(tmp_path / "none", tmp_path / "none") is None


def test_parse_vm_stat() -> None:
    text = (
        "Mach Virtual Memory Statistics: (page size of 16384 bytes)\n"
        "Pages free:                               10000.\n"
        "Pages active:                            500000.\n"
        "Pages inactive:                           20000.\n"
        "Pages speculative:                         3000.\n"
        "Pages throttled:                              0.\n"
        "Pages wired down:                        100000.\n"
        "Pages purgeable:                           1000.\n"
    )
    assert parse_vm_stat(text) == 16384 * (10000 + 20000 + 3000 + 1000)
    assert parse_vm_stat("nothing useful") is None


def test_available_memory_on_this_machine_is_plausible() -> None:
    """Runs the reader for this OS in CI (Linux and Windows)."""
    available = available_memory()
    if available is not None:
        assert 16 << 20 <= available <= 1 << 50
