"""Public command entrypoint for investment-tool."""

from __future__ import annotations

import sys
from typing import Sequence

from investment_tool.workflow.run import main as workflow_main


def main(argv: Sequence[str] | None = None) -> int:
    return workflow_main(list(argv if argv is not None else sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
