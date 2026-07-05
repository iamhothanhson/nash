import os

LOSS_FILTER = os.getenv("LOSS_FILTER", "false").lower() in ("true", "1", "yes")