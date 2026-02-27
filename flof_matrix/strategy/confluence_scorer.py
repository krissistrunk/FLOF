"""Confluence Scorer (M06, Component) — The brain of the system.

Pure computation, NO I/O. Performance budget: < 500 microseconds total.

Execution order:
  1. G1: Premium/Discount gate
  2. G2: Inducement gate
  3. G3: Chop Detector gate
  4. Tier 1 scoring (10 pts max) + gate check (>= 7)
  5. Tier 2 scoring (4 pts max, gated by T16)
  6. Tier 3 scoring (3 pts max)
  7. Grade assignment
  8. Position sizing
"""

from __future__ import annotations

from dataclasses import dataclass

from flof_matrix.core.types import (
    Grade,
    OrderType,
    POIType,
    TradeDirection,
)
from flof_matrix.core.data_types import POI, TradeSignal


@dataclass
class ScoringContext:
    """All inputs needed for confluence scoring. Pre-computed by callers."""

    # G1: Premium/Discount
    premium_discount: str  # 'premium' or 'discount'

    # G2: Inducement
    has_inducement: bool

    # G3: Chop
    is_chop: bool

    # POI
    poi: POI

    # Tier 1 inputs
    trend_aligned: bool
    regime: str  # 'aligned', 'conflicted', 'neutral'
    has_liquidity_sweep: bool
    is_fresh_poi: bool
    has_choch: bool
    choch_displacement_exceeds_atr: bool
    order_flow_score: int  # 0, 1, or 2
    in_killzone: bool

    # Tier 2 inputs (Velez)
    velez_enabled: bool
    has_20sma_halt: bool
    has_flat_200sma: bool
    has_elephant_bar: bool
    has_micro_trend: bool

    # Tier 3 inputs
    has_vwap_confluence: bool
    is_flip_zone: bool
    has_liquidity_near_target: bool

    # Config thresholds
    tier1_gate_minimum: int = 7
    a_plus_min: int = 14
    a_min: int = 12
    b_min: int = 9

    # Gate overrides
    g1_enabled: bool = True
    g1_bonus: int = 1  # Tier 1 bonus points when in correct premium/discount zone
    g2_required: bool = True

    # Scoring points (from config)
    trend_full: int = 2
    trend_reduced: int = 1
    sweep_points: int = 2
    fresh_poi_points: int = 1
    choch_points: int = 2
    of_full_points: int = 2
    of_partial_points: int = 1
    killzone_points: int = 1
    sma_halt_points: int = 1
    flat_200_points: int = 1
    elephant_bar_points: int = 1
    micro_trend_points: int = 1
    vwap_sd_points: int = 1
    flip_zone_points: int = 1
    liquidity_target_points: int = 1

    # Sizing
    a_plus_risk: float = 0.020
    a_risk: float = 0.015
    b_risk: float = 0.010
    cascade_active: bool = False
    cascade_multiplier: float = 0.50

    # Shadow mode
    shadow_position_size_pct: float = 0.005

    # Execution
    entry_price: float = 0.0
    stop_price: float = 0.0
    target_price: float = 0.0
    order_type: OrderType = OrderType.MWP


class ConfluenceScorer:
    """Pure computation scorer. No I/O, no state mutation beyond return values."""

    def __init__(self) -> None:
        self.last_rejection: dict | None = None

    def score(self, ctx: ScoringContext) -> TradeSignal | None:
        """Run full confluence scoring pipeline. Returns TradeSignal or None if gated.

        Performance budget: < 500 microseconds.
        """
        self.last_rejection = None

        # === GATE 1: Premium/Discount ===
        if ctx.g1_enabled and not self._check_g1(ctx):
            direction = "LONG" if ctx.poi.direction == TradeDirection.LONG else "SHORT"
            self.last_rejection = {
                "gate": "G1_premium_discount",
                "reason": f"{direction} rejected: price in {ctx.premium_discount} zone",
            }
            return None

        # === GATE 2: Inducement ===
        if not self._check_g2(ctx):
            self.last_rejection = {
                "gate": "G2_inducement",
                "reason": "No liquidity sweep (inducement) before POI tap",
            }
            return None

        # === GATE 3: Chop Detector ===
        if not self._check_g3(ctx):
            self.last_rejection = {
                "gate": "G3_chop_detector",
                "reason": "Session detected as choppy — no directional entry",
            }
            return None

        # === TIER 1: Core SMC + Order Flow (10 pts max) ===
        tier1 = self._score_tier1(ctx)

        # Tier 1 gate check
        if tier1 < ctx.tier1_gate_minimum:
            self.last_rejection = {
                "gate": "T1_gate_minimum",
                "reason": f"Tier 1 score {tier1} < minimum {ctx.tier1_gate_minimum}",
                "tier1_score": tier1,
            }
            return None

        # === TIER 2: Velez Momentum Layers (4 pts max) ===
        tier2 = self._score_tier2(ctx)

        # === TIER 3: VWAP + Liquidity (3 pts max) ===
        tier3 = self._score_tier3(ctx)

        total = tier1 + tier2 + tier3

        # === GRADE ASSIGNMENT ===
        grade = self._assign_grade(total, ctx)

        # Synthetic MA POIs capped at B
        if ctx.poi.type == POIType.SYNTHETIC_MA and grade in (Grade.A_PLUS, Grade.A):
            grade = Grade.B

        # Grade C = NO TRADE
        if grade == Grade.C:
            self.last_rejection = {
                "gate": "grade_C",
                "reason": f"Total score {total} (T1:{tier1} T2:{tier2} T3:{tier3}) below B minimum {ctx.b_min}",
                "tier1_score": tier1,
            }
            return None

        # === POSITION SIZING ===
        size_pct = self._calculate_size(grade, ctx)

        return TradeSignal(
            direction=ctx.poi.direction,
            poi=ctx.poi,
            entry_price=ctx.entry_price,
            stop_price=ctx.stop_price,
            target_price=ctx.target_price,
            grade=grade,
            score_total=total,
            score_tier1=tier1,
            score_tier2=tier2,
            score_tier3=tier3,
            position_size_pct=size_pct,
            order_type=ctx.order_type,
        )

    def score_shadow(self, ctx: ScoringContext) -> tuple[TradeSignal, list[str]]:
        """Shadow scoring: always returns a signal, collecting failed gates instead of rejecting.

        Returns (TradeSignal, list_of_failed_gate_names). Empty list = clean trade.
        """
        failed_gates: list[str] = []

        # === GATE 1: Premium/Discount ===
        if not self._check_g1(ctx):
            failed_gates.append("G1_premium_discount")

        # === GATE 2: Inducement ===
        if not self._check_g2(ctx):
            failed_gates.append("G2_inducement")

        # === GATE 3: Chop Detector ===
        if not self._check_g3(ctx):
            failed_gates.append("G3_chop_detector")

        # === TIER 1: Core SMC + Order Flow (10 pts max) ===
        tier1 = self._score_tier1(ctx)

        if tier1 < ctx.tier1_gate_minimum:
            failed_gates.append("T1_gate_minimum")

        # === TIER 2 & 3 ===
        tier2 = self._score_tier2(ctx)
        tier3 = self._score_tier3(ctx)
        total = tier1 + tier2 + tier3

        # === GRADE ASSIGNMENT ===
        grade = self._assign_grade(total, ctx)

        # Synthetic MA POIs capped at B
        if ctx.poi.type == POIType.SYNTHETIC_MA and grade in (Grade.A_PLUS, Grade.A):
            grade = Grade.B

        # Grade C: record failure, force to B so we get a valid signal
        if grade == Grade.C:
            failed_gates.append("grade_C")
            grade = Grade.B

        # === POSITION SIZING ===
        if failed_gates:
            size_pct = ctx.shadow_position_size_pct
        else:
            size_pct = self._calculate_size(grade, ctx)

        signal = TradeSignal(
            direction=ctx.poi.direction,
            poi=ctx.poi,
            entry_price=ctx.entry_price,
            stop_price=ctx.stop_price,
            target_price=ctx.target_price,
            grade=grade,
            score_total=total,
            score_tier1=tier1,
            score_tier2=tier2,
            score_tier3=tier3,
            position_size_pct=size_pct,
            order_type=ctx.order_type,
        )
        return signal, failed_gates

    def _check_g1(self, ctx: ScoringContext) -> bool:
        """G1: Premium/Discount — longs in discount only, shorts in premium only."""
        if ctx.poi.direction == TradeDirection.LONG:
            return ctx.premium_discount == "discount"
        else:
            return ctx.premium_discount == "premium"

    def _check_g2(self, ctx: ScoringContext) -> bool:
        """G2: Inducement — must have liquidity sweep before POI tap."""
        if not ctx.g2_required:
            return True
        return ctx.has_inducement

    def _check_g3(self, ctx: ScoringContext) -> bool:
        """G3: Chop Detector — no entry during chop."""
        return not ctx.is_chop

    def _score_tier1(self, ctx: ScoringContext) -> int:
        """Tier 1: Core SMC + Order Flow (10 pts max)."""
        score = 0

        # +2/+1 Trend Alignment
        if ctx.trend_aligned:
            if ctx.regime == "aligned":
                score += ctx.trend_full
            elif ctx.regime == "conflicted":
                score += ctx.trend_reduced
            else:
                score += ctx.trend_full  # neutral = full points

        # +2 Major Liquidity Sweep
        if ctx.has_liquidity_sweep:
            score += ctx.sweep_points

        # +1 Fresh POI
        if ctx.is_fresh_poi:
            score += ctx.fresh_poi_points

        # +2 1m CHOCH with Displacement
        if ctx.has_choch and ctx.choch_displacement_exceeds_atr:
            score += ctx.choch_points

        # +2/+1 Order Flow Confirmation
        if ctx.order_flow_score >= 2:
            score += ctx.of_full_points
        elif ctx.order_flow_score == 1:
            score += ctx.of_partial_points

        # +1 Killzone Timing
        if ctx.in_killzone:
            score += ctx.killzone_points

        # +1 Premium/Discount bonus (when G1 is demoted from gate to scoring)
        if not ctx.g1_enabled and self._check_g1(ctx):
            score += ctx.g1_bonus

        return score

    def _score_tier2(self, ctx: ScoringContext) -> int:
        """Tier 2: Velez Momentum Layers (4 pts max, gated by T16)."""
        if not ctx.velez_enabled:
            return 0

        score = 0
        if ctx.has_20sma_halt:
            score += ctx.sma_halt_points
        if ctx.has_flat_200sma:
            score += ctx.flat_200_points
        if ctx.has_elephant_bar:
            score += ctx.elephant_bar_points
        if ctx.has_micro_trend:
            score += ctx.micro_trend_points
        return score

    def _score_tier3(self, ctx: ScoringContext) -> int:
        """Tier 3: VWAP + Liquidity (3 pts max)."""
        score = 0
        if ctx.has_vwap_confluence:
            score += ctx.vwap_sd_points
        if ctx.is_flip_zone:
            score += ctx.flip_zone_points
        if ctx.has_liquidity_near_target:
            score += ctx.liquidity_target_points
        return score

    def _assign_grade(self, total: int, ctx: ScoringContext) -> Grade:
        """Assign grade based on total score."""
        if total >= ctx.a_plus_min:
            return Grade.A_PLUS
        elif total >= ctx.a_min:
            return Grade.A
        elif total >= ctx.b_min:
            return Grade.B
        else:
            return Grade.C

    def _calculate_size(self, grade: Grade, ctx: ScoringContext) -> float:
        """Calculate position size percentage based on grade."""
        if grade == Grade.A_PLUS:
            size = ctx.a_plus_risk
        elif grade == Grade.A:
            size = ctx.a_risk
        else:
            size = ctx.b_risk

        # Type B cascade override
        if ctx.cascade_active:
            size *= ctx.cascade_multiplier

        return size
