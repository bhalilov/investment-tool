"""Public command entrypoint for investment-tool."""

from __future__ import annotations

import sys
from typing import Sequence

from investment_tool.runtime.env import load_env
from investment_tool.runtime.paths import repo_root


def main(argv: Sequence[str] | None = None) -> int:
    load_env(repo_root() / ".env")
    args = list(argv if argv is not None else sys.argv[1:])
    from investment_tool.workflow.run import main as workflow_main

    if not args:
        return workflow_main(["--help"])
    if args[0] != "workflow":
        print("Use: investment-tool workflow <update|rebuild|check|doctor>", file=sys.stderr)
        return 2
    return workflow_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
