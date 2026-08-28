"""CLI 진행 상황 출력. 표준 logging으로 통일해 print를 흩뿌리지 않는다."""
from __future__ import annotations
import logging
import sys

_CONFIGURED = False


def get_logger(name: str = "aptfinder") -> logging.Logger:
    global _CONFIGURED
    if not _CONFIGURED:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        root = logging.getLogger("aptfinder")
        root.setLevel(logging.INFO)
        root.addHandler(handler)
        root.propagate = False
        _CONFIGURED = True
    return logging.getLogger(name if name.startswith("aptfinder") else f"aptfinder.{name}")
