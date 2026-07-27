import os

MARKET_STRUCTURE_DEBUG = os.getenv("MARKET_STRUCTURE_DEBUG", "false").lower() == "true"
BREAKOUT_PIPELINE_DEBUG = os.getenv("BREAKOUT_PIPELINE_DEBUG", "false").lower() == "true"
BREAKOUT_REJECTION_DEBUG = os.getenv("BREAKOUT_REJECTION_DEBUG", "false").lower() == "true"
