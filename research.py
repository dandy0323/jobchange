"""CLI entry point (thin wrapper).

Usage:
    python research.py research --company "株式会社XX"
    python research.py research -c "株式会社XX" -j ./job.pdf

`pip install -e .` 後は `company-research research -c ...` でも実行可能。
"""

from __future__ import annotations

import sys
from pathlib import Path

# `src/` を PYTHONPATH に追加（editable install 前でも動作させる）
_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from research.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
