@dataclass
class PreTradeResult:
    allowed: bool
    reason: str | None = None
    severity: str = "INFO"