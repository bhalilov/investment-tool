# Interfaces

Interfaces expose investment-tool capabilities to external systems.

Planned interface families:

- `mcp/`: MCP server/protocol surfaces for the investing brain.
- `custom_gpt/`: API/action surfaces for Custom GPT experiments.
- future app connectors or local APIs.

## Rules

- Keep reusable pipeline, retrieval, analysis, and runtime behavior in their
  owning packages.
- Interface modules should adapt shared capabilities for outside callers, not
  duplicate capture, analysis, or storage logic.
- Prototype interfaces in feature worktrees and merge them to `main` only after
  the underlying contracts are stable.
