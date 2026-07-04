from config.strategy_filter_config import BREAKOUT_FILTER_THRESHOLDS, SWEEP_FILTER_THRESHOLDS

ST = SWEEP_FILTER_THRESHOLDS

# Config key -> signal attribute name mapping for dynamic threshold checks
_FILTER_FIELDS = {
    "min_adx_15m": "adx",
    "min_volume_ratio": "volume_ratio",
    "min_breakout_strength": "breakout_strength",
    "min_body_ratio": "body_ratio",
    "min_regime_confidence": "regime_confidence",
}


def breakout_filter(signal) -> tuple[bool, list[str]]:
    cfg = BREAKOUT_FILTER_THRESHOLDS
    if not cfg.get("enabled", True):
        return True, []

    reasons = []

    for cfg_key, sig_attr in _FILTER_FIELDS.items():
        threshold = cfg.get(cfg_key)
        if threshold is None:
            continue
        value = getattr(signal, sig_attr, None)
        if value is None:
            continue
        if value < threshold:
            reasons.append(f"{cfg_key}: {value:.4f} < {threshold}")

    if cfg.get("require_trend_alignment"):
        aligned = getattr(signal, "trend_aligned", None)
        if aligned is not None and not aligned:
            reasons.append("Trend not aligned with breakout direction.")

    accepted = len(reasons) == 0
    return accepted, reasons


def sweep_filter(signal) -> tuple[bool, list[str]]:
    if not ST.get("enabled", True):
        return True, []

    reasons = []

    if signal.atr_percentile > ST["max_atr_percentile"]:
        reasons.append(
            f"ATR percentile ({signal.atr_percentile}) > {ST['max_atr_percentile']}."
        )

    if signal.volume_ratio < ST["min_volume_ratio"]:
        reasons.append(
            f"Volume ratio ({signal.volume_ratio:.2f}) < {ST['min_volume_ratio']:.2f}."
        )

    accepted = len(reasons) == 0
    return accepted, reasons
