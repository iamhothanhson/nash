from __future__ import annotations

import pandas as pd

VOLUME_RATIO_WINDOW = 20


def _volume_ratio(volume: pd.Series, window: int = VOLUME_RATIO_WINDOW) -> float:
    if len(volume) < window + 1:
        return 1.0
    current = float(volume.iloc[-1])
    avg = float(volume.iloc[-(window + 1):-1].mean())
    return current / max(avg, 1e-12)
