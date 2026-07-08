import importlib
import sys


def __getattr__(name: str):
    if name in ("RiskManager", "RiskResult", "compute_risk_multiplier"):
        module = importlib.import_module("risk_manager.risk_manager")
        return getattr(module, name)
    raise AttributeError(f"module 'risk_manager' has no attribute {name!r}")


def __dir__():
    return ["RiskManager", "RiskResult", "compute_risk_multiplier"]

