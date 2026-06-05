"""Public command entrypoint for investment-tool."""

from __future__ import annotations

import sys
from typing import Sequence

from investment_tool.runtime.env import load_env
from investment_tool.runtime.paths import repo_root


def main(argv: Sequence[str] | None = None) -> int:
    load_env(repo_root() / ".env")
    args = list(argv if argv is not None else sys.argv[1:])
    if args and args[0] == "storage":
        from investment_tool.workflow.storage import main as storage_main

        return storage_main(args[1:])
    from investment_tool.workflow.run import main as workflow_main

    return workflow_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
