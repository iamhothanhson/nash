"""
Loss Reason Analyzer — post-trade analytics for losing positions.

Consumes enriched loss records from collect_position_analysis_data.collect_regime_for_trade() and
determines the single most likely failure reason with structured evidence.

Post-trade analytics only — never affects live trading.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from config.constants import BREAKOUT, BREAKOUT_RETEST, PULLBACK

LossReason = Literal[
    "False Breakout",
    "Weak Trend",
    "Low Volume",
    "Overextended Entry",
    "High Volatility",
    "Poor Exit",
    "Unknown",
]

_LOSS_REASONS: tuple[LossReason, ...] = (
    "False Breakout",
    "Weak Trend",
    "Low Volume",
    "Overextended Entry",
    "High Volatility",
    "Poor Exit",
    "Unknown",
)

_LOSS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "position_analysis"
_LOSS_FILE = _LOSS_DIR / "position_analysis_data.json"


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


def _sev(score_weight: float) -> str:
    if score_weight >= 30:
        return "High"
    if score_weight >= 15:
        return "Medium"
    return "Low"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class LossReasonResult:
    loss_reason: LossReason
    confidence: int
    evidence: list[dict[str, str]] = field(default_factory=list)


@dataclass
class LossReasonSummary:
    total_losses: int = 0
    counts: dict[str, int] = field(default_factory=lambda: {r: 0 for r in _LOSS_REASONS})
    percentages: dict[str, float] = field(default_factory=dict)

    def add(self, reason: str) -> None:
        self.total_losses += 1
        if reason in self.counts:
            self.counts[reason] += 1
        else:
            self.counts[reason] = self.counts.get(reason, 0) + 1

    def finalize(self) -> None:
        t = max(self.total_losses, 1)
        self.percentages = {k: round(v / t * 100, 1) for k, v in self.counts.items()}


# ---------------------------------------------------------------------------
# Loss Reason Analyzer
# ---------------------------------------------------------------------------


class LossReasonAnalyzer:
    """
    Determines the single most likely reason a losing trade failed.
    Consumes the enriched record from collect_position_analysis_data.collect_market_regime().
    """

    def analyze_from_record(self, record: dict[str, Any]) -> LossReasonResult:
        mr = record.get("market_regime", {})
        tc = record.get("trade_context", {})
        tp = record.get("trade_performance", {})

        direction = tc.get("side", "LONG")
        setup_type_raw = record.get("strategy_setup", "")
        setup_type = self._parse_setup_type(setup_type_raw)
        is_long = direction.upper() == "LONG"

        mae_r = tp.get("mae_r", 0.0)
        mfe_r = tp.get("mfe_r", 0.0)
        bars_held = tc.get("bars_held", 0)
        entry_price = tc.get("entry_price", 0.0)
        stop_loss = tc.get("stop_loss", 0.0)
        risk_pct = tc.get("risk_pct", 0.0)

        scores: dict[str, tuple[float, list[dict[str, str]]]] = {}

        self._score_false_breakout(scores, setup_type, mr, is_long, mfe_r)
        self._score_weak_trend(scores, mr)
        self._score_low_volume(scores, mr)
        self._score_overextended(scores, mr, is_long)
        self._score_high_volatility(scores, mr)
        self._score_poor_exit(scores, mfe_r, mae_r, bars_held, entry_price, stop_loss, risk_pct, tc)

        if not scores:
            return LossReasonResult(
                loss_reason="Unknown",
                confidence=25,
                evidence=[
                    {"severity": "Low", "message": "No predefined loss reason met the confidence threshold."},
                    {"severity": "Low", "message": "Multiple metrics conflicted, preventing a reliable classification."},
                ],
            )

        if "False Breakout" in scores and "Weak Trend" in scores:
            fb_s, fb_ev = scores["False Breakout"]
            wt_s, _ = scores["Weak Trend"]
            if wt_s >= 55 and fb_s < 70:
                fb_s = max(0, fb_s - 15)
                scores["False Breakout"] = (fb_s, fb_ev)

        best = max(scores, key=lambda k: scores[k][0])
        score, ev = scores[best]
        return LossReasonResult(
            loss_reason=best,
            confidence=int(min(score, 100)),
            evidence=ev,
        )

    @staticmethod
    def _parse_setup_type(raw: str) -> str:
        s = raw.strip().upper().replace("_", " ").replace("-", " ")
        if "BREAKOUT RETEST" in s or BREAKOUT_RETEST in s:
            return BREAKOUT_RETEST
        if BREAKOUT in s:
            return BREAKOUT
        if PULLBACK in s:
            return PULLBACK
        if "sweep" in s or "liquidity" in s:
            return "liquidity_sweep_reversal"
        return s

    # -- False Breakout -------------------------------------------------------

    def _score_false_breakout(
        self,
        scores: dict[str, tuple[float, list[dict[str, str]]]],
        setup_type: str,
        mr: dict[str, Any],
        is_long: bool,
        mfe_r: float,
    ) -> None:
        if setup_type not in (BREAKOUT, BREAKOUT_RETEST):
            return

        s = 0.0
        ev: list[dict[str, str]] = []
        vol = mr.get("volume_ratio", 1.0)
        rsi = mr.get("rsi", 50.0)
        mkt = mr.get("market_structure", "Range")
        adx = mr.get("adx_1h", 0.0)
        ema_slope = mr.get("ema20_slope_1h", 0.0)

        if vol < 0.8:
            s += 35
            ev.append({"severity": "High", "message": f"Volume ratio = {vol:.2f} < required 1.25."})
        elif vol < 1.0:
            s += 20
            ev.append({"severity": "Medium", "message": f"Volume ratio = {vol:.2f} < required 1.25."})

        if (is_long and rsi > 65) or (not is_long and rsi < 35):
            s += 25
            side_txt = "overbought" if is_long else "oversold"
            ev.append({"severity": "Medium", "message": f"RSI = {rsi:.1f} ({side_txt}) at entry — buying at elevated levels."})

        if (is_long and mkt == "LHLL") or (not is_long and mkt == "HHHL"):
            s += 20
            ev.append({"severity": "Medium", "message": f"Market structure ({mkt}) opposed the {('long' if is_long else 'short')} direction."})

        if mfe_r < 0.3:
            s += 20
            ev.append({"severity": "Low", "message": f"MFE = {mfe_r:.2f}R before reversal — failed to gain momentum."})

        if abs(ema_slope) < 0.0005:
            s -= 10

        if s >= 25:
            scores["False Breakout"] = (s, sorted(ev, key=lambda x: {"High": 0, "Medium": 1, "Low": 2}[x["severity"]]))

    # -- Weak Trend -----------------------------------------------------------

    def _score_weak_trend(
        self,
        scores: dict[str, tuple[float, list[dict[str, str]]]],
        mr: dict[str, Any],
    ) -> None:
        s = 0.0
        ev: list[dict[str, str]] = []
        adx = mr.get("adx_1h", 0.0)
        ema_slope = mr.get("ema20_slope_1h", 0.0)
        mkt = mr.get("market_structure", "Range")
        vol = mr.get("volume_ratio", 1.0)
        rsi = mr.get("rsi", 50.0)

        if adx < 20:
            s += 35
            ev.append({"severity": "High", "message": f"ADX (1h) = {adx:.1f} < trend threshold 20."})
        elif adx < 23:
            s += 15
            ev.append({"severity": "Medium", "message": f"ADX (1h) = {adx:.1f} < trend threshold 20."})

        if abs(ema_slope) < 0.0005:
            s += 20
            ev.append({"severity": "Medium", "message": f"EMA20 slope (1h) = {ema_slope:.4f} (nearly flat)."})

        if mkt == "Range":
            s += 20
            ev.append({"severity": "Medium", "message": "Market structure = Range (no directional edge)."})

        if 45 <= rsi <= 55:
            s += 10
            ev.append({"severity": "Low", "message": f"RSI = {rsi:.1f} (neutral momentum, no trend catalyst)."})

        if vol < 0.7:
            s += 10
            ev.append({"severity": "Low", "message": f"Volume ratio = {vol:.2f} (low conviction confirms weak trend)."})

        if s >= 25:
            scores["Weak Trend"] = (s, sorted(ev, key=lambda x: {"High": 0, "Medium": 1, "Low": 2}[x["severity"]]))

    # -- Low Volume -----------------------------------------------------------

    def _score_low_volume(
        self,
        scores: dict[str, tuple[float, list[dict[str, str]]]],
        mr: dict[str, Any],
    ) -> None:
        s = 0.0
        ev: list[dict[str, str]] = []
        vol = mr.get("volume_ratio", 1.0)
        mkt = mr.get("market_structure", "Range")
        adx = mr.get("adx_1h", 0.0)

        vol_threshold = 1.25

        if vol < 0.5:
            s += 50
            ev.append({"severity": "High", "message": f"Volume ratio = {vol:.2f} < required {vol_threshold:.2f}."})
        elif vol < 0.7:
            s += 35
            ev.append({"severity": "High", "message": f"Volume ratio = {vol:.2f} < required {vol_threshold:.2f}."})
        elif vol < 0.85:
            s += 20
            ev.append({"severity": "Medium", "message": f"Volume ratio = {vol:.2f} < required {vol_threshold:.2f}."})
        elif vol < 1.0:
            s += 10
            ev.append({"severity": "Low", "message": f"Volume ratio = {vol:.2f} < required {vol_threshold:.2f}."})

        if adx < 22 and vol < 0.85:
            s += 15
            ev.append({"severity": "Medium", "message": f"Volume ratio = {vol:.2f} with ADX (1h) = {adx:.1f} — no institutional volume for a breakout."})

        if mkt not in ("HHHL", "LHLL"):
            s -= 5

        if s >= 25:
            scores["Low Volume"] = (s, sorted(ev, key=lambda x: {"High": 0, "Medium": 1, "Low": 2}[x["severity"]]))

    # -- Overextended Entry ---------------------------------------------------

    def _score_overextended(
        self,
        scores: dict[str, tuple[float, list[dict[str, str]]]],
        mr: dict[str, Any],
        is_long: bool,
    ) -> None:
        s = 0.0
        ev: list[dict[str, str]] = []
        rsi = mr.get("rsi", 50.0)

        if is_long and rsi > 70:
            s += 40
            ev.append({"severity": "High", "message": f"RSI = {rsi:.1f} (overbought — entry was at extreme levels)."})
        elif not is_long and rsi < 30:
            s += 40
            ev.append({"severity": "High", "message": f"RSI = {rsi:.1f} (oversold — entry was at extreme levels)."})
        elif is_long and rsi > 65:
            s += 20
            ev.append({"severity": "Medium", "message": f"RSI = {rsi:.1f} (elevated — late entry into the move)."})
        elif not is_long and rsi < 35:
            s += 20
            ev.append({"severity": "Medium", "message": f"RSI = {rsi:.1f} (low — late entry into the move)."})

        ema_slope = mr.get("ema20_slope_1h", 0.0)
        if abs(ema_slope) < 0.001 and s > 0:
            s -= 10

        if s >= 25:
            scores["Overextended Entry"] = (s, sorted(ev, key=lambda x: {"High": 0, "Medium": 1, "Low": 2}[x["severity"]]))

    # -- High Volatility ------------------------------------------------------

    def _score_high_volatility(
        self,
        scores: dict[str, tuple[float, list[dict[str, str]]]],
        mr: dict[str, Any],
    ) -> None:
        s = 0.0
        ev: list[dict[str, str]] = []
        atr_pctl = mr.get("atr_percentile", 50)
        atr_pct = mr.get("atr_percent", 0.0)

        if atr_pctl > 90:
            s += 40
            ev.append({"severity": "High", "message": f"ATR percentile = {atr_pctl} (extremely high volatility)."})
        elif atr_pctl > 80:
            s += 30
            ev.append({"severity": "High", "message": f"ATR percentile = {atr_pctl} (elevated volatility)."})
        elif atr_pctl > 70:
            s += 15
            ev.append({"severity": "Medium", "message": f"ATR percentile = {atr_pctl} (above-normal volatility)."})

        if atr_pct > 1.5:
            s += 15
            ev.append({"severity": "Medium", "message": f"ATR = {atr_pct:.2f}% of price (wide-ranging bars)."})

        adx = mr.get("adx_1h", 0.0)
        if adx > 30 and atr_pctl > 70:
            s += 10
            ev.append({"severity": "Low", "message": f"Trend strength (ADX = {adx:.1f}) combined with high ATR produced unpredictable swings."})

        if s >= 25:
            scores["High Volatility"] = (s, sorted(ev, key=lambda x: {"High": 0, "Medium": 1, "Low": 2}[x["severity"]]))

    # -- Poor Exit ------------------------------------------------------------

    def _score_poor_exit(
        self,
        scores: dict[str, tuple[float, list[dict[str, str]]]],
        mfe_r: float,
        mae_r: float,
        bars_held: int,
        entry_price: float,
        stop_loss: float,
        risk_pct: float,
        tc: dict[str, Any],
    ) -> None:
        s = 0.0
        ev: list[dict[str, str]] = []
        tp_hit = tc.get("tp_hit", False)

        trade_went_right = mfe_r > 0.5 and abs(mae_r) < 0.3
        trade_strongly_right = mfe_r > 1.0

        if trade_went_right:
            s += 35
            ev.append({"severity": "High", "message": f"MFE = +{mfe_r:.2f}R before closing at SL — trade direction was correct."})

        if trade_strongly_right and tp_hit:
            s += 20
            ev.append({"severity": "Medium", "message": f"MFE = +{mfe_r:.2f}R and TP was hit but position still closed at a loss."})
        elif trade_strongly_right:
            s += 15
            ev.append({"severity": "Medium", "message": f"MFE = +{mfe_r:.2f}R before reversal — exit timing missed the move."})

        if bars_held < 3:
            s += 15
            ev.append({"severity": "Medium", "message": f"Position held only {bars_held} bars — insufficient time for thesis to develop."})

        if 0 < risk_pct < 0.4:
            s += 15
            ev.append({"severity": "Low", "message": f"Stop distance = {risk_pct:.2f}% (tight stop vulnerable to noise)."})

        if mfe_r > 2.0:
            s += 10
            ev.append({"severity": "Low", "message": f"Trailing stop gave back {mfe_r:.2f}R of unrealized profit before hitting SL."})

        if s >= 25:
            scores["Poor Exit"] = (s, sorted(ev, key=lambda x: {"High": 0, "Medium": 1, "Low": 2}[x["severity"]]))


# ---------------------------------------------------------------------------
# Convenience: analyze a record and append analysis
# ---------------------------------------------------------------------------


def analyze_loss_record(record: dict[str, Any]) -> dict[str, Any]:
    """
    Run LossReasonAnalyzer on a collected loss record.
    Returns a copy with ``analysis`` appended.
    """
    analyzer = LossReasonAnalyzer()
    result = analyzer.analyze_from_record(record)
    out = dict(record)
    out["analysis"] = {
        "primary_reason": result.loss_reason,
        "confidence": result.confidence,
        "evidence": result.evidence,
    }
    return out


def append_analysis_to_stored_record(record: dict[str, Any]) -> dict[str, Any]:
    """
    Find the matching record in loss_position/ and append analysis to it.
    If the record already has analysis, it is replaced.
    """
    _LOSS_DIR.mkdir(parents=True, exist_ok=True)

    opened = record.get("trade_context", {}).get("opened", "")
    if not opened:
        return record

    enriched = analyze_loss_record(record)
    _write_single_analysis_file(_LOSS_FILE, enriched, record)
    return enriched


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def format_loss_reason_summary(summary: LossReasonSummary) -> str:
    lines = [
        "=" * 60,
        "LOSS REASON ANALYSIS SUMMARY",
        "=" * 60,
        f"Total Losses: {summary.total_losses}",
        "-" * 60,
        "{:<25} {:>7} {:>10}".format("Reason", "Count", "Percent"),
        "-" * 25 + " " + "-" * 7 + " " + "-" * 10,
    ]
    for reason in _LOSS_REASONS:
        c = summary.counts.get(reason, 0)
        p = summary.percentages.get(reason, 0.0)
        if c > 0:
            lines.append(f"{reason:<25} {c:>7} {p:>8.1f}%")
    lines.append("-" * 60)
    top_reason = max(
        ((r, summary.counts.get(r, 0)) for r in _LOSS_REASONS),
        key=lambda x: x[1],
    )
    if top_reason[1] > 0:
        pct = summary.percentages.get(top_reason[0], 0.0)
        lines.append(f"Primary Weakness: {top_reason[0]} ({pct:.1f}% of losses)")
    lines.append("=" * 60)
    return "\n".join(lines)


def _parse_loss_dt(display: str) -> datetime | None:
    try:
        return datetime.strptime(display.strip(), "%b-%d-%Y %H:%M:%S").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _write_single_analysis_file(path: Path, enriched: dict, original: dict) -> None:
    """Upsert a single record into the analysis file by (coin, opened, closed)."""
    try:
        records: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        records = []
    if not isinstance(records, list):
        records = []
    coin = original.get("coin", "")
    opened = original.get("trade_context", {}).get("opened", "")
    closed = original.get("trade_context", {}).get("closed", "")
    for i, r in enumerate(records):
        if (
            r.get("coin") == coin
            and r.get("trade_context", {}).get("opened") == opened
            and r.get("trade_context", {}).get("closed") == closed
        ):
            records[i] = enriched
            break
    else:
        records.append(enriched)
    path.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")


def analyze_all_loss_records() -> LossReasonSummary:
    """Run analysis on every record in position_analysis/ and return a summary."""
    if not _LOSS_FILE.exists():
        return LossReasonSummary()

    summary = LossReasonSummary()
    analyzer = LossReasonAnalyzer()

    try:
        all_records: list[dict[str, Any]] = json.loads(_LOSS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return LossReasonSummary()
    if not isinstance(all_records, list):
        return LossReasonSummary()

    changed = False
    for i, record in enumerate(all_records):
        if not isinstance(record, dict):
            continue
        if "analysis" in record:
            reason = record["analysis"].get("primary_reason", "Unknown")
            summary.add(reason)
            continue
        result = analyzer.analyze_from_record(record)
        all_records[i]["analysis"] = {
            "primary_reason": result.loss_reason,
            "confidence": result.confidence,
            "evidence": result.evidence,
        }
        summary.add(result.loss_reason)
        changed = True

    if changed:
        _LOSS_FILE.write_text(json.dumps(all_records, indent=2) + "\n", encoding="utf-8")

    summary.finalize()
    return summary
