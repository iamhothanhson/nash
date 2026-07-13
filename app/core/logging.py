from __future__ import annotations

import logging
from datetime import date
from pathlib import Path


class DailyFileHandler(logging.Handler):
    def __init__(self, log_dir: str = "logs"):
        super().__init__()

        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self._current_date: date | None = None
        self._file_handler: logging.FileHandler | None = None

        self._open_file()

    def _open_file(self) -> None:
        today = date.today()

        if self._current_date == today:
            return

        if self._file_handler:
            self._file_handler.close()

        filename = self.log_dir / f"{today:%Y-%m-%d}.log"

        self._file_handler = logging.FileHandler(
            filename,
            encoding="utf-8",
        )

        self._file_handler.setFormatter(
            logging.Formatter("%(message)s")
        )

        self._current_date = today

    def emit(self, record: logging.LogRecord) -> None:
        self._open_file()

        if self._file_handler:
            self._file_handler.emit(record)


def setup_logging(
    log_dir: str = "logs",
    level: int = logging.INFO,
    console: bool = True,
) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    root.addHandler(DailyFileHandler(log_dir))

    if console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-8s %(name)s %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        root.addHandler(console_handler)