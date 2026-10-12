"""Tests for the PalmGuard CLI (Task T01)."""

import pytest

import palmguard
from palmguard.cli import WRITABLE_DIRS, check_duckdb_window, main, run_doctor


def test_package_version():
    assert palmguard.__version__ == "0.1.0"


def test_duckdb_window_check():
    assert check_duckdb_window()


def test_doctor_passes_and_creates_directories(tmp_path, capsys):
    assert run_doctor(tmp_path) == 0
    for d in WRITABLE_DIRS:
        assert (tmp_path / d).is_dir()
    assert "Doctor result: PASS" in capsys.readouterr().out


def test_cli_requires_command():
    with pytest.raises(SystemExit):
        main([])


def test_cli_pipeline_run_and_subcommands(repo_copy, capsys):
    """Test CLI pipeline run, forecast, monitor, and report commands."""
    exit_pipe = main(["pipeline", "run", "--offline"])
    assert exit_pipe == 0
    out = capsys.readouterr().out
    assert "Pipeline execution complete" in out

    exit_fc = main(["forecast"])
    assert exit_fc == 0
    out_fc = capsys.readouterr().out
    assert "PalmGuard Published Forecasts" in out_fc
    assert "palm_wb_myr" in out_fc

    exit_mon = main(["monitor"])
    assert exit_mon == 0
    assert "Monitoring audit complete" in capsys.readouterr().out

    exit_rep = main(["report", "--type", "holdout"])
    assert exit_rep == 0
    assert "Forecast Model Comparison" in capsys.readouterr().out
