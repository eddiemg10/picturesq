from pathlib import Path

import pytest
import typer
from pydantic import ValidationError
from typer.testing import CliRunner

from picturesq.cli.config import EXIT_INVALID, load_config_or_exit
from picturesq.config import (
    CONFIG_FILENAME,
    ConfigError,
    OutputConfig,
    ProjectConfig,
    dump_project_config,
    load_project_config,
    save_project_config,
)

# --- defaults and validation ------------------------------------------------------------------


def test_defaults_match_the_project_plan() -> None:
    config = ProjectConfig()
    assert config.version == 1
    assert config.decode.demosaic == "ahd"
    assert config.decode.highlight_mode == "blend"
    assert config.export.outputs["web"] == OutputConfig(long_edge=2048, quality=90)
    assert config.export.outputs["archive"] == OutputConfig(long_edge=None, quality=95)
    assert config.export.enabled == ["web", "archive"]


def test_empty_mapping_is_the_defaults() -> None:
    assert ProjectConfig.model_validate({}) == ProjectConfig()


def test_partial_section_keeps_other_defaults() -> None:
    config = ProjectConfig.model_validate({"decode": {"demosaic": "dcb"}})
    assert config.decode.demosaic == "dcb"
    assert config.decode.highlight_mode == "blend"


@pytest.mark.parametrize(
    "data",
    [
        {"version": 2},
        {"decode": {"demosaic": "magic"}},
        {"decode": {"demosiac": "ahd"}},  # typo: unknown keys are errors
        {"surprise": 1},
        {"export": {"outputs": {"web": {"quality": 0}}}},
        {"export": {"outputs": {"web": {"quality": 101}}}},
        {"export": {"outputs": {"web": {"long_edge": 0}}}},
        {"export": {"outputs": {"Web Large": {}}, "enabled": []}},  # not snake_case
        {"export": {"enabled": ["web", "print"]}},  # unknown output
        {"export": {"enabled": ["web", "web"]}},
    ],
)
def test_invalid_config_is_rejected(data: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate(data)


def test_assignment_is_validated() -> None:
    config = ProjectConfig()
    with pytest.raises(ValidationError):
        config.export.outputs["web"].quality = 500


# --- YAML round trip ----------------------------------------------------------------------------


def test_round_trip_defaults(tmp_path: Path) -> None:
    path = tmp_path / CONFIG_FILENAME
    save_project_config(ProjectConfig(), path)
    assert load_project_config(path) == ProjectConfig()


def test_round_trip_custom(tmp_path: Path) -> None:
    config = ProjectConfig.model_validate(
        {
            "decode": {"demosaic": "dht", "highlight_mode": "reconstruct"},
            "export": {
                "outputs": {"web": {"long_edge": 1600, "quality": 85}, "print": {"quality": 100}},
                "enabled": ["print"],
            },
        }
    )
    path = tmp_path / CONFIG_FILENAME
    save_project_config(config, path)
    assert load_project_config(path) == config
    # Saving what we loaded is byte-for-byte stable.
    assert dump_project_config(load_project_config(path)) == path.read_text(encoding="utf-8")


def test_yaml_keeps_model_order_and_null(tmp_path: Path) -> None:
    text = dump_project_config(ProjectConfig())
    assert text.index("version") < text.index("decode") < text.index("export")
    assert "long_edge: null" in text


def test_save_replaces_existing_and_leaves_no_temp_files(tmp_path: Path) -> None:
    path = tmp_path / CONFIG_FILENAME
    path.write_text("old: content\n", encoding="utf-8")
    save_project_config(ProjectConfig(), path)
    assert load_project_config(path) == ProjectConfig()
    assert [p.name for p in tmp_path.iterdir()] == [CONFIG_FILENAME]


def test_failed_save_keeps_the_old_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / CONFIG_FILENAME
    save_project_config(ProjectConfig(), path)
    before = path.read_text(encoding="utf-8")

    def broken_replace(src: str, dst: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("picturesq.config.yaml_io.os.replace", broken_replace)
    changed = ProjectConfig.model_validate({"decode": {"demosaic": "vng"}})
    with pytest.raises(OSError, match="disk full"):
        save_project_config(changed, path)
    assert path.read_text(encoding="utf-8") == before
    assert [p.name for p in tmp_path.iterdir()] == [CONFIG_FILENAME]


# --- load errors --------------------------------------------------------------------------------


def test_empty_file_gives_defaults(tmp_path: Path) -> None:
    path = tmp_path / CONFIG_FILENAME
    path.write_text("", encoding="utf-8")
    assert load_project_config(path) == ProjectConfig()


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("decode: [unclosed", "not valid YAML"),
        ("- a\n- list\n", "must be a mapping"),
        ("export:\n  outputs:\n    web: {quality: 120}\n", "export.outputs.web.quality"),
        ("decode:\n  demosiac: ahd\n", "decode.demosiac"),
    ],
)
def test_load_errors_are_clear(tmp_path: Path, text: str, message: str) -> None:
    path = tmp_path / CONFIG_FILENAME
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match=message):
        load_project_config(path)


def test_validation_error_names_the_file_and_value(tmp_path: Path) -> None:
    path = tmp_path / CONFIG_FILENAME
    path.write_text("export:\n  outputs:\n    web: {quality: 120}\n", encoding="utf-8")
    with pytest.raises(ConfigError) as caught:
        load_project_config(path)
    assert CONFIG_FILENAME in str(caught.value)
    assert "120" in str(caught.value)


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="does not exist"):
        load_project_config(tmp_path / CONFIG_FILENAME)


# --- CLI contract: exit 2 -----------------------------------------------------------------------


def _probe_app() -> typer.Typer:
    app = typer.Typer()

    @app.command()
    def probe(project: Path) -> None:
        config = load_config_or_exit(project)
        typer.echo(config.decode.demosaic)

    return app


def test_cli_loads_valid_config(tmp_path: Path) -> None:
    save_project_config(ProjectConfig(), tmp_path / CONFIG_FILENAME)
    result = CliRunner().invoke(_probe_app(), [str(tmp_path)])
    assert result.exit_code == 0
    assert "ahd" in result.output


def test_cli_invalid_config_exits_2(tmp_path: Path) -> None:
    (tmp_path / CONFIG_FILENAME).write_text("decode: {demosaic: magic}\n", encoding="utf-8")
    result = CliRunner().invoke(_probe_app(), [str(tmp_path)])
    assert result.exit_code == EXIT_INVALID == 2
    assert "decode.demosaic" in result.output
