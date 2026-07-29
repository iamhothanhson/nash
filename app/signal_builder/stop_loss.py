from app.setup_builder.config import A, A_PLUS
@staticmethod
def _max_sl_distance(grade: int) -> float:
    if grade == A_PLUS:
        return 0.03      # 3%
    if grade == A:
        return 0.025     # 2.5%
    return 0.02          # 2%

@classmethod
def compute_stop_loss(entry, anchor, atr, direction, atr_mult):
    if direction == "LONG":
        sl = anchor - atr * atr_mult
        dist = (entry - sl) / entry
    else:
        sl = anchor + atr * atr_mult
        dist = (sl - entry) / entry

    return sl, dist