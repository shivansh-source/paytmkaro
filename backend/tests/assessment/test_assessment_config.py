"""Config and registry validity: weights, bands and the one-entry-per-parameter contract."""

import json

import pytest

from app.assessment import REGISTRY, load_config
from app.assessment.config import CONFIG_PATH, AssessmentConfig, Band, ParameterConfig, band_for
from app.assessment.registry import CATEGORIES

REFERENCE_PENDING_WEIGHTS = {  # the only weights documented in the reference scorecard
    "fn.unit_economics": 3, "cp.warehouse_status": 2, "cp.sector_view": 1, "sp.promoter_net_worth": 1,
    "bc.macro_shock": 1, "bc.margin_facility": 3, "bc.facility_trend": 1, "rb.adverse_flags": 3,
    "rb.voluntary_disclosure": 1, "rb.company_assets": 1, "rb.responsiveness": 1,
}


def test_config_loads_and_is_versioned_and_uncalibrated():
    cfg = load_config()
    assert cfg.config_version
    assert cfg.calibrated is False
    assert "UNCALIBRATED" in cfg.note


def test_registry_and_config_have_identical_ids():
    cfg = load_config()
    ids = [p.id for p in REGISTRY]
    assert len(ids) == len(set(ids)) == 51
    assert set(ids) == set(cfg.parameters)


def test_every_parameter_has_a_known_category():
    assert {p.category for p in REGISTRY} <= set(CATEGORIES)


def test_weights_are_positive_and_sources_valid():
    for pid, pc in load_config().parameters.items():
        assert pc.weight > 0, pid
        assert pc.weight_source in ("placeholder", "reference"), pid


def test_reference_weights_are_exactly_the_eleven_documented_ones():
    cfg = load_config()
    reference = {pid: pc.weight for pid, pc in cfg.parameters.items() if pc.weight_source == "reference"}
    assert reference == REFERENCE_PENDING_WEIGHTS
    assert sorted(reference.values(), reverse=True) == [3, 3, 3, 2, 1, 1, 1, 1, 1, 1, 1]
    # Three of the eleven can be computed now that the bureau report and sanction letter have envelopes;
    # the other eight still wait for something no document supplies (or for a document type we lack).
    now_computable = {p.id for p in REGISTRY if p.id in reference and p.computable}
    assert now_computable == {"bc.margin_facility", "bc.facility_trend", "rb.adverse_flags"}


def test_computable_parameters_have_bands_that_cover_every_value():
    cfg = load_config()
    for p in REGISTRY:
        bands = cfg.parameters[p.id].bands
        if p.computable:
            assert bands, p.id
            assert all(0 <= b.points <= 100 for b in bands)
            if bands[0].value is None:
                assert band_for(bands, -1e12) and band_for(bands, 1e12)  # catch-all exists


def test_numeric_bands_are_ordered_so_first_match_is_monotonic():
    for p in REGISTRY:
        bands = load_config().parameters[p.id].bands
        if not bands or bands[0].value is not None:
            continue
        mins = [b.min for b in bands if b.min is not None and b.max is None]
        maxs = [b.max for b in bands if b.max is not None and b.min is None]
        assert mins == sorted(mins, reverse=True), p.id
        assert maxs == sorted(maxs), p.id


def test_invalid_configs_are_rejected():
    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    bad = json.loads(json.dumps(raw))
    bad["grades"] = list(reversed(bad["grades"]))
    with pytest.raises(ValueError):
        AssessmentConfig.model_validate(bad)
    with pytest.raises(ValueError):  # last numeric band must be a catch-all
        ParameterConfig(weight=1, weight_source="placeholder", bands=[Band(label="x", points=1, min=0)])
    with pytest.raises(ValueError):  # weight must be positive
        ParameterConfig(weight=0, weight_source="placeholder")


def test_band_for_first_match_wins_and_ranges_work():
    bands = load_config().parameters["bc.gst_bank_consistency"].bands
    assert band_for(bands, 1.0).points == 100
    assert band_for(bands, 0.78).points == 75
    assert band_for(bands, 1.5).points == 40
    assert band_for(bands, 2.5).points == 10
    foir = load_config().parameters["bc.foir"].bands
    assert band_for(foir, 0.20).points == 100  # upper bound inclusive
    assert band_for(foir, 0.2001).points == 80
