"""
Tests for the analyze subcommand of the headless CLI.

Covers the single-folder argument parser and the run_analyze_cli exit paths.
"""

import pytest

from core.services.cli.BatchCLI import (
    _build_analyze_parser, _build_analysis_config, run_analyze_cli,
    RESOLUTION_PRESETS,
)


# --- analyze parser ---------------------------------------------------------

def test_analyze_parser_builds_config_from_flags():
    """The analyze parser feeds _build_analysis_config like the batch one."""
    args = _build_analyze_parser().parse_args([
        '--input', 'in', '--output', 'out', '--algorithm', 'ColorRange',
        '--min-area', '40', '--resolution', '50%',
    ])
    config = _build_analysis_config(args)
    assert config['algorithm']['name'] == 'ColorRange'
    assert config['min_area'] == 40
    assert config['processing_resolution'] == RESOLUTION_PRESETS['50%']


def test_analyze_parser_options_parsed():
    """--option entries become typed algorithm options."""
    args = _build_analyze_parser().parse_args([
        '--input', 'in', '--output', 'out', '--algorithm', 'ThermalRange',
        '--option', 'minTemp=20.5',
    ])
    config = _build_analysis_config(args)
    assert config['options']['minTemp'] == 20.5


def test_analyze_parser_rejects_coordinator_flags():
    """The analyze subcommand does not accept the batch/coordinator-only flags."""
    with pytest.raises(SystemExit):
        _build_analyze_parser().parse_args([
            '--input', 'in', '--output', 'out', '--no-coordinator',
        ])


# --- run_analyze_cli --------------------------------------------------------

def test_run_analyze_cli_missing_input(tmp_path):
    """run_analyze_cli returns exit code 1 when the input folder is missing."""
    code = run_analyze_cli([
        '--input', str(tmp_path / 'does_not_exist'),
        '--output', str(tmp_path / 'out'),
        '--algorithm', 'ColorRange',
    ])
    assert code == 1


def test_run_analyze_cli_requires_algorithm(tmp_path):
    """run_analyze_cli returns exit code 1 when no algorithm is resolved."""
    src = tmp_path / 'in'
    src.mkdir()
    code = run_analyze_cli([
        '--input', str(src), '--output', str(tmp_path / 'out'),
    ])
    assert code == 1
