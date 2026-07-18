"""Tests for Chemical Processing industry constants."""

from app.services.industry.chemical.constants import CHEM_PROCESS_FLOW, CHEM_PROCESS_COUNT_KEYS


def test_chem_process_flow_has_unique_paths():
    paths = [path for _, _, path, _ in CHEM_PROCESS_FLOW]
    assert len(paths) == len(set(paths))


def test_chem_process_count_keys_cover_core_gates():
    assert "feasibility" in CHEM_PROCESS_COUNT_KEYS
    assert "routing" in CHEM_PROCESS_COUNT_KEYS
    assert "execution" in CHEM_PROCESS_COUNT_KEYS
    assert "dispatch" in CHEM_PROCESS_COUNT_KEYS
