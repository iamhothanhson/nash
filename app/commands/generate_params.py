from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

IGNORED_KEYS = {
    "BINANCE_TESTNET_API_KEY",
    "BINANCE_TESTNET_SECRET",
    "BINANCE_API_KEY",
    "BINANCE_SECRET",
    "OPENAI_API_KEY"
}


def _parse_env(env_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key:
            values[key] = value
    return values


def _to_python_literal(raw: str) -> int | float | str:
    value = raw.strip()
    if value == "":
        return ""

    if "." not in value and "e" not in value.lower():
        try:
            return int(value)
        except ValueError:
            pass

    try:
        return float(value)
    except ValueError:
        return value


def _format_assignment(key: str, value: int | float | str) -> str:
    if isinstance(value, str):
        return f"{key} = {value!r}"
    return f"{key} = {value}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Save strategy params from .env")
    parser.add_argument("--roi", required=True, help="ROI label to include in output filename")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent.parent
    env_path = project_root / ".env"
    if not env_path.exists():
        raise FileNotFoundError(f".env file not found at {env_path}")

    env_values = _parse_env(env_path)
    filtered_items = [(k, v) for k, v in env_values.items() if k not in IGNORED_KEYS]

    out_dir = project_root / "parameters"
    out_dir.mkdir(parents=True, exist_ok=True)

    date_part = datetime.now().strftime("%m-%d-%Y")
    out_path = out_dir / f"{date_part}_ROI-{args.roi}.py"

    lines = [
        "# Auto-generated from .env by generate_params.py",
    ]
    for key, raw_value in filtered_items:
        lines.append(_format_assignment(key, _to_python_literal(raw_value)))
    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Saved params to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
