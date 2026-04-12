"""
BELFORT-PAPER-SIM-REGIME-LEARNING-01 acceptance tests.

A. belfort_regime_learning module — structure and public API
B. compute_regime_metrics() — expected shape and today_only filter
C. current_strategy_profile() — expected keys and extended_hours label
D. maybe_record_regime_snapshot() — tick interval gate
E. market_regime field in paper_exec records
F. market_regime = "closed_sim" in sim records
G. trading_loop._run_regime_snapshot function exists
H. observability bridge exports read_regime_metrics, read_strategy_profile
I. neighborhood._belfort_state() keys: belfort_regime_metrics, belfort_strategy_profile
J. Regime chip HTML element and CSS present in neighborhood
K. Strategy profile HTML element and CSS present in neighborhood
L. Peter handler imports read_regime_metrics, read_strategy_profile
M. regime_line added to Peter belfort_status summary construction
N. Auto-snapshot wires to trading_loop on tick cadence
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

NEIGHBORHOOD  = ROOT / "app" / "routes" / "neighborhood.py"
TRADING_LOOP  = ROOT / "app" / "trading_loop.py"
HANDLERS      = ROOT / "peter" / "handlers.py"
OBS_BRIDGE    = ROOT / "observability" / "belfort_summary.py"
PAPER_EXEC    = ROOT / "app" / "belfort_paper_exec.py"
SIM_MODULE    = ROOT / "app" / "belfort_sim.py"
REGIME_MODULE = ROOT / "app" / "belfort_regime_learning.py"

_NH  = NEIGHBORHOOD.read_text()
_TL  = TRADING_LOOP.read_text()
_PH  = HANDLERS.read_text()
_OBS = OBS_BRIDGE.read_text()
_PE  = PAPER_EXEC.read_text()
_SIM = SIM_MODULE.read_text()
_RM  = REGIME_MODULE.read_text()


# ── A. Module structure ───────────────────────────────────────────────────────

class TestRegimeLearningModule:
    def test_module_file_exists(self):
        assert REGIME_MODULE.exists()

    def test_compute_regime_metrics_defined(self):
        assert "def compute_regime_metrics" in _RM

    def test_current_strategy_profile_defined(self):
        assert "def current_strategy_profile" in _RM

    def test_maybe_record_regime_snapshot_defined(self):
        assert "def maybe_record_regime_snapshot" in _RM

    def test_write_regime_snapshot_defined(self):
        assert "def _write_regime_snapshot" in _RM

    def test_min_ticks_constant_is_20(self):
        assert "_MIN_TICKS_BETWEEN_SNAPSHOTS = 20" in _RM

    def test_learning_history_path_correct(self):
        assert '"learning_history.jsonl"' in _RM

    def test_extended_is_not_supported(self):
        assert '"not_supported"' in _RM


# ── B. compute_regime_metrics ─────────────────────────────────────────────────

class TestComputeRegimeMetrics:
    def test_returns_three_keys(self):
        from app.belfort_regime_learning import compute_regime_metrics
        result = compute_regime_metrics()
        assert "regular" in result
        assert "closed_sim" in result
        assert "extended" in result

    def test_extended_is_not_supported(self):
        from app.belfort_regime_learning import compute_regime_metrics
        result = compute_regime_metrics()
        assert result["extended"] == "not_supported"

    def test_regular_has_correct_keys(self):
        from app.belfort_regime_learning import compute_regime_metrics
        reg = compute_regime_metrics()["regular"]
        for key in ("submitted", "gated", "errored", "total"):
            assert key in reg, f"Missing key: {key}"

    def test_closed_sim_has_correct_keys(self):
        from app.belfort_regime_learning import compute_regime_metrics
        sim = compute_regime_metrics()["closed_sim"]
        for key in ("fills", "buys", "sells", "holds", "ticks"):
            assert key in sim, f"Missing key: {key}"

    def test_today_only_default_is_true(self):
        """Function signature defaults to today_only=True."""
        import inspect
        from app.belfort_regime_learning import compute_regime_metrics
        sig = inspect.signature(compute_regime_metrics)
        assert sig.parameters["today_only"].default is True

    def test_does_not_raise_on_missing_files(self):
        """Should return zero-filled dicts if log files don't exist."""
        from app.belfort_regime_learning import compute_regime_metrics
        result = compute_regime_metrics()
        assert isinstance(result["regular"]["total"], int)
        assert isinstance(result["closed_sim"]["ticks"], int)


# ── C. current_strategy_profile ──────────────────────────────────────────────

class TestCurrentStrategyProfile:
    def test_returns_expected_keys(self):
        from app.belfort_regime_learning import current_strategy_profile
        p = current_strategy_profile()
        for key in ("current_regime", "paper_regime", "sim_regime",
                    "regime_metrics", "fitness_regular", "fitness_sim", "extended_hours"):
            assert key in p, f"Missing key: {key}"

    def test_paper_regime_is_regular(self):
        from app.belfort_regime_learning import current_strategy_profile
        assert current_strategy_profile()["paper_regime"] == "regular"

    def test_sim_regime_is_closed_sim(self):
        from app.belfort_regime_learning import current_strategy_profile
        assert current_strategy_profile()["sim_regime"] == "closed_sim"

    def test_extended_hours_is_not_supported(self):
        from app.belfort_regime_learning import current_strategy_profile
        assert current_strategy_profile()["extended_hours"] == "not_supported"

    def test_fitness_fields_are_strings(self):
        from app.belfort_regime_learning import current_strategy_profile
        p = current_strategy_profile()
        assert isinstance(p["fitness_regular"], str)
        assert isinstance(p["fitness_sim"], str)

    def test_current_regime_is_valid_string(self):
        from app.belfort_regime_learning import current_strategy_profile
        cur = current_strategy_profile()["current_regime"]
        assert isinstance(cur, str)
        assert len(cur) > 0


# ── D. maybe_record_regime_snapshot ──────────────────────────────────────────

class TestMaybeRecordRegimeSnapshot:
    def test_returns_false_below_interval(self):
        from app.belfort_regime_learning import maybe_record_regime_snapshot
        import app.belfort_regime_learning as rl
        rl._last_snapshot_tick = 0
        # Tick 5 < MIN_TICKS_BETWEEN_SNAPSHOTS (20)
        result = maybe_record_regime_snapshot(5)
        assert result is False

    def test_returns_true_at_interval(self):
        """At tick 20 with last=0, interval is met — should attempt write."""
        from app.belfort_regime_learning import maybe_record_regime_snapshot
        import app.belfort_regime_learning as rl
        from unittest.mock import patch
        rl._last_snapshot_tick = 0
        with patch("app.belfort_regime_learning._write_regime_snapshot") as mock_write:
            result = maybe_record_regime_snapshot(20)
        assert result is True
        mock_write.assert_called_once()

    def test_updates_last_snapshot_tick(self):
        from app.belfort_regime_learning import maybe_record_regime_snapshot
        import app.belfort_regime_learning as rl
        from unittest.mock import patch
        rl._last_snapshot_tick = 0
        with patch("app.belfort_regime_learning._write_regime_snapshot"):
            maybe_record_regime_snapshot(20)
        assert rl._last_snapshot_tick == 20

    def test_never_raises(self):
        """Failure in _write_regime_snapshot must be swallowed."""
        from app.belfort_regime_learning import maybe_record_regime_snapshot
        import app.belfort_regime_learning as rl
        from unittest.mock import patch
        rl._last_snapshot_tick = 0
        with patch("app.belfort_regime_learning._write_regime_snapshot", side_effect=RuntimeError("boom")):
            result = maybe_record_regime_snapshot(20)
        assert result is False


# ── E. market_regime in paper_exec records ───────────────────────────────────

class TestPaperExecMarketRegime:
    def test_market_regime_field_in_build_record(self):
        assert "market_regime" in _PE

    def test_market_regime_derived_from_session_type(self):
        """The market_regime field is derived from session_type."""
        assert "session_type" in _PE
        # The regime assignment line references _session
        assert "_session" in _PE or "session_type" in _PE

    def test_regular_session_maps_to_regular(self):
        """When session_type=regular, market_regime should be 'regular'."""
        assert '"regular"' in _PE


# ── F. market_regime in sim records ──────────────────────────────────────────

class TestSimMarketRegime:
    def test_closed_sim_label_in_sim_module(self):
        assert '"closed_sim"' in _SIM

    def test_market_regime_in_fill_records(self):
        assert "market_regime" in _SIM

    def test_closed_sim_in_both_fill_types(self):
        """market_regime: closed_sim must appear in buy, sell, and hold records."""
        count = _SIM.count('"closed_sim"')
        assert count >= 3, f"Expected market_regime in buy/sell/hold records, found {count} occurrences"


# ── G. trading_loop._run_regime_snapshot ─────────────────────────────────────

class TestTradingLoopRegimeSnapshot:
    def test_run_regime_snapshot_function_defined(self):
        assert "def _run_regime_snapshot" in _TL

    def test_calls_maybe_record_regime_snapshot(self):
        assert "maybe_record_regime_snapshot" in _TL

    def test_called_on_tick_modulo_20(self):
        assert "_ticks % 20" in _TL

    def test_called_inside_loop_body(self):
        loop_start = _TL.find("def _loop_body")
        loop_section = _TL[loop_start:][:900]
        assert "_run_regime_snapshot" in loop_section

    def test_imports_belfort_regime_learning(self):
        snapshot_fn_start = _TL.find("def _run_regime_snapshot")
        snapshot_fn = _TL[snapshot_fn_start:][:400]
        assert "belfort_regime_learning" in snapshot_fn


# ── H. Observability bridge exports ──────────────────────────────────────────

class TestObsBridgeExports:
    def test_read_regime_metrics_defined(self):
        assert "def read_regime_metrics" in _OBS

    def test_read_strategy_profile_defined(self):
        assert "def read_strategy_profile" in _OBS

    def test_read_regime_metrics_is_transport_safe(self):
        """Must import from app.belfort_regime_learning inside try block."""
        fn_start = _OBS.find("def read_regime_metrics")
        fn_section = _OBS[fn_start:][:500]
        assert "belfort_regime_learning" in fn_section
        assert "try" in fn_section

    def test_read_strategy_profile_is_transport_safe(self):
        fn_start = _OBS.find("def read_strategy_profile")
        fn_section = _OBS[fn_start:][:500]
        assert "belfort_regime_learning" in fn_section
        assert "try" in fn_section

    def test_read_regime_metrics_fallback_has_correct_structure(self):
        """Fallback dict must have regular, closed_sim, extended keys."""
        fallback_area = _OBS[_OBS.find("def read_regime_metrics"):][:700]
        assert '"regular"' in fallback_area
        assert '"closed_sim"' in fallback_area
        assert '"not_supported"' in fallback_area


# ── I. neighborhood._belfort_state() keys ────────────────────────────────────

class TestNeighborhoodBelfortStateKeys:
    def test_belfort_regime_metrics_key_set(self):
        assert "belfort_regime_metrics" in _NH

    def test_belfort_strategy_profile_key_set(self):
        assert "belfort_strategy_profile" in _NH

    def test_reads_from_observability_bridge(self):
        assert "read_regime_metrics" in _NH
        assert "read_strategy_profile" in _NH


# ── J. Regime chip HTML and CSS ──────────────────────────────────────────────

class TestRegimeChipUi:
    def test_regime_chip_element_present(self):
        assert 'id="belfort-regime-chip"' in _NH

    def test_regime_chip_css_defined(self):
        assert ".bregime-chip" in _NH

    def test_regime_regular_css_class(self):
        assert ".bregime-regular" in _NH

    def test_regime_closed_css_class(self):
        assert ".bregime-closed" in _NH

    def test_regime_pre_market_css_class(self):
        assert ".bregime-pre_market" in _NH

    def test_regime_chip_js_update(self):
        assert "belfort-regime-chip" in _NH
        assert "regimeChipEl" in _NH

    def test_regime_labels_in_js(self):
        assert "PRE-MKT" in _NH
        assert "AFTER-HRS" in _NH
        assert "REGULAR" in _NH
        assert "CLOSED" in _NH


# ── K. Strategy profile HTML and CSS ─────────────────────────────────────────

class TestStrategyProfileUi:
    def test_strategy_profile_element_present(self):
        assert 'id="belfort-strategy-profile"' in _NH

    def test_strategy_profile_css_defined(self):
        assert ".bstrategy-profile" in _NH

    def test_strategy_profile_js_updates(self):
        assert "stratEl" in _NH
        assert "stratProfile" in _NH

    def test_extended_hours_not_supported_in_js(self):
        assert "Extended hours: paper not supported" in _NH or "extended hours" in _NH.lower()


# ── L. Peter handler imports ──────────────────────────────────────────────────

class TestPeterHandlerImports:
    def test_imports_read_regime_metrics(self):
        assert "read_regime_metrics" in _PH

    def test_imports_read_strategy_profile(self):
        assert "read_strategy_profile" in _PH


# ── M. Peter belfort_status regime line ──────────────────────────────────────

class TestPeterBelfortStatusRegimeLine:
    def test_regime_line_variable_defined(self):
        assert "regime_line" in _PH

    def test_regime_line_appended_to_summary(self):
        # belfort_status is a long function — search from sim_line concat
        sim_concat = _PH.find("+ sim_line")
        assert sim_concat != -1, "sim_line concat not found"
        after_sim = _PH[sim_concat:][:300]
        assert "+ regime_line" in after_sim, "regime_line not appended after sim_line in summary"

    def test_regime_label_in_peter(self):
        assert "Market regime" in _PH

    def test_extended_not_supported_in_peter(self):
        assert "not supported" in _PH

    def test_calls_read_strategy_profile(self):
        regime_section = _PH[_PH.find("regime_line"):][:400]
        assert "read_strategy_profile" in regime_section


# ── N. Auto-snapshot tick cadence ─────────────────────────────────────────────

class TestAutoSnapshotTick:
    def test_snapshot_every_20_ticks(self):
        assert "% 20 == 0" in _TL

    def test_snapshot_condition_calls_run_regime_snapshot(self):
        mod_section = _TL[_TL.find("% 20 == 0"):][:100]
        assert "_run_regime_snapshot" in mod_section

    def test_snapshot_is_nonfatal(self):
        """_run_regime_snapshot must have try/except."""
        fn_start = _TL.find("def _run_regime_snapshot")
        fn_section = _TL[fn_start:][:500]
        assert "try" in fn_section
        assert "except" in fn_section
