"""Toggle dependency tree for FLOF Matrix feature toggles.

Encodes the parent→child dependency relationships from flof_base.toml lines 57-66:
    T01 → T02 → T03
    T07 → T08, T09, T18
    T16 → T12, T13, T14, T15
    T19 → T20
    T18 + T19 → T21  (both parents must be ON)
    T29 → T30
    T31 → T32
    T46 → T47

Rule: Parent OFF → all children forced OFF.
"""

from __future__ import annotations

# Maps toggle_id → list of parent toggle_ids that ALL must be ON.
# Single parent: [parent]. Multi-parent (AND): [parent1, parent2].
TOGGLE_DEPENDENCIES: dict[str, list[str]] = {
    # T01 → T02 → T03
    "T02": ["T01"],
    "T03": ["T02"],
    # T07 → T08, T09, T18
    "T08": ["T07"],
    "T09": ["T07"],
    "T18": ["T07"],
    # T16 → T12, T13, T14, T15
    "T12": ["T16"],
    "T13": ["T16"],
    "T14": ["T16"],
    "T15": ["T16"],
    # T19 → T20
    "T20": ["T19"],
    # T18 + T19 → T21  (AND dependency)
    "T21": ["T18", "T19"],
    # T29 → T30
    "T30": ["T29"],
    # T31 → T32
    "T32": ["T31"],
    # T46 → T47
    "T47": ["T46"],
}

# Safety toggles that are LOCKED ON when live_mode=true
SAFETY_TOGGLES = {"T24", "T25", "T26", "T27", "T28"}

# Map toggle IDs (e.g. "T01") to their TOML key paths
TOGGLE_KEY_MAP: dict[str, str] = {
    "T01": "toggles.structure.T01_htf_structure_mapper",
    "T02": "toggles.structure.T02_htf_regime_filter",
    "T03": "toggles.structure.T03_synthetic_ma_poi",
    "T04": "toggles.structure.T04_poi_freshness_tracking",
    "T05": "toggles.structure.T05_liquidity_sweep_detection",
    "T06": "toggles.execution.T06_choch_detection",
    "T07": "toggles.execution.T07_order_flow_confirmation",
    "T08": "toggles.execution.T08_absorption_detection",
    "T09": "toggles.execution.T09_whale_watch_filter",
    "T10": "toggles.execution.T10_killzone_time_gate",
    "T11": "toggles.execution.T11_fast_move_switch",
    "T12": "toggles.velez.T12_20sma_halt_confluence",
    "T13": "toggles.velez.T13_flat_200sma_confluence",
    "T14": "toggles.velez.T14_elephant_bar_confirmation",
    "T15": "toggles.velez.T15_20sma_micro_trend",
    "T16": "toggles.velez.T16_all_velez_layers",
    "T17": "toggles.risk.T17_hvn_lvn_stop_placement",
    "T18": "toggles.risk.T18_conditional_tape_failure",
    "T19": "toggles.risk.T19_structural_node_trail",
    "T20": "toggles.risk.T20_rbi_gbi_hold_filter",
    "T21": "toggles.risk.T21_20sma_health_check",
    "T22": "toggles.risk.T22_200sma_exit_watch_zone",
    "T23": "toggles.risk.T23_phase1_fixed_partial",
    "T24": "toggles.safety.T24_oco_bracket_enforcement",
    "T25": "toggles.safety.T25_anti_spam_rate_limiter",
    "T26": "toggles.safety.T26_fat_finger_position_limit",
    "T27": "toggles.safety.T27_daily_drawdown_breaker",
    "T28": "toggles.safety.T28_stale_data_monitor",
    "T29": "toggles.safety.T29_sudden_move_classifier",
    "T30": "toggles.safety.T30_cascade_position_override",
    "T31": "toggles.structure.T31_mtf_poi_hierarchy",
    "T32": "toggles.structure.T32_poi_clustering",
    "T33": "toggles.execution.T33_schema_shifting",
    "T34": "toggles.execution.T34_proximity_halo_dynamic",
    "T35": "toggles.risk.T35_toxicity_timer",
    "T36": "toggles.risk.T36_a_plus_scaleout",
    "T37": "toggles.multi_asset.T37_cross_asset_correlation",
    "T38": "toggles.multi_asset.T38_macro_dump_detector",
    "T39": "toggles.structure.T39_extreme_decisional_tagging",
    "T40": "toggles.structure.T40_unicorn_poi_detection",
    "T41": "toggles.multi_asset.T41_earnings_shield",
    "T42": "toggles.multi_asset.T42_funding_rate_monitor",
    "T43": "toggles.multi_asset.T43_oi_delta_tracker",
    "T44": "toggles.multi_asset.T44_forex_session_overlap",
    "T45": "toggles.multi_asset.T45_multi_exchange_arb",
    "T46": "toggles.options.T46_options_routing",
    "T47": "toggles.options.T47_gex_aware_selling",
    "T48": "toggles.risk.T48_toxicity_exit",
    "T49": "toggles.options.T49_forex_carry_trade",
    "T50": "toggles.options.T50_iron_condor_chop",
}


class ToggleRegistry:
    """Evaluates toggle states respecting dependency chains and safety locks."""

    def __init__(self, config_getter, live_mode: bool = False):
        """
        Args:
            config_getter: Callable that takes a dotted key and returns the value.
            live_mode: When True, safety toggles T24-T28 are forced ON.
        """
        self._get = config_getter
        self._live_mode = live_mode

    def is_enabled(self, toggle_id: str) -> bool:
        """Check if a toggle is enabled, respecting dependency chain and safety locks."""
        # Safety toggles forced ON in live mode
        if self._live_mode and toggle_id in SAFETY_TOGGLES:
            return True

        # Check own value
        key = TOGGLE_KEY_MAP.get(toggle_id)
        if key is None:
            return False
        own_value = self._get(key, False)
        if not own_value:
            return False

        # Check all parents (AND logic — all parents must be ON)
        parents = TOGGLE_DEPENDENCIES.get(toggle_id, [])
        for parent_id in parents:
            if not self.is_enabled(parent_id):
                return False

        return True

    def validate(self) -> list[str]:
        """Return list of validation errors (empty = valid)."""
        errors = []
        for toggle_id, key in TOGGLE_KEY_MAP.items():
            val = self._get(key, None)
            if val is not None and not isinstance(val, bool):
                errors.append(f"{toggle_id} ({key}): expected bool, got {type(val).__name__}")

        # Check for orphan children enabled without parent
        for child_id, parent_ids in TOGGLE_DEPENDENCIES.items():
            child_key = TOGGLE_KEY_MAP.get(child_id)
            if child_key and self._get(child_key, False):
                for parent_id in parent_ids:
                    parent_key = TOGGLE_KEY_MAP.get(parent_id)
                    if parent_key and not self._get(parent_key, False):
                        errors.append(
                            f"{child_id} is ON but parent {parent_id} is OFF "
                            f"(will be forced OFF at runtime)"
                        )
        return errors

    def enforce_safety_locks(self, config_dict: dict) -> None:
        """Force safety toggles ON when live_mode=true. Mutates config_dict."""
        if not self._live_mode:
            return
        for toggle_id in SAFETY_TOGGLES:
            key = TOGGLE_KEY_MAP[toggle_id]
            parts = key.split(".")
            d = config_dict
            for part in parts[:-1]:
                d = d.setdefault(part, {})
            d[parts[-1]] = True
