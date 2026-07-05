def position_side_for_direction(direction: str, *, hedge_mode: bool) -> str | None:
    if not hedge_mode:
        return None
    return "LONG" if direction.upper() == "LONG" else "SHORT"
