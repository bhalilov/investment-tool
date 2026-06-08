# Workstreams

This file maps the major product workstreams so separate Codex chats can work
without stepping on each other.

## Core / Production

Worktree:

```text
core/
```

Branch:

```text
main
```

Purpose:

- production sync/jobs;
- accepted shared code;
- bug fixes that need to ship immediately;
- small shared foundations after review.

Avoid:

- speculative MCP/API/AI code;
- unreviewed design experiments;
- running paid/side-effect jobs without explicit intent.

## Architecture / Docs

Worktree:

```text
architecture/
```

Branch:

```text
docs/architecture-brain-design
```

Purpose:

- high-level architecture;
- implementation-ready specs;
- documentation cleanup;
- product/backlog shaping.

Allowed areas:

- `README.md`;
- `docs/`;
- config/prompt/schema docs when needed.

Avoid:

- production code changes unless explicitly approved;
- runtime data jobs;
- feature implementation.

## MCP

Worktree:

```text
mcp/
```

Branch:

```text
feat/mcp-investing-brain
```

Likely home:

```text
src/investment_tool/interfaces/mcp/
```

Purpose:

- expose investing-brain capabilities through MCP;
- reuse shared runtime/config/reporting/retrieval code;
- define tools/resources only after the evidence model is clear enough.

Avoid:

- duplicating data access;
- hardcoding production paths;
- merging to `main` without acceptance.

## Custom GPT API

Worktree:

```text
custom-gpt/
```

Branch:

```text
feat/custom-gpt-api
```

Likely home:

```text
src/investment_tool/interfaces/custom_gpt/
```

Purpose:

- prototype a local/API surface for Custom GPT actions;
- reuse the same retrieval/query layer planned for MCP where possible.

Avoid:

- recreating the deleted legacy action server shape blindly;
- exposing unstable evidence fields as permanent API contracts.

## AI Pass 1

Worktree:

```text
ai-pass1/
```

Branch:

```text
feat/ai-pass1
```

Likely homes:

```text
src/investment_tool/analysis/
prompts/
schemas/
config/ai/
```

Purpose:

- implement reusable thread AI pass mechanics;
- run Phase 1 without vector retrieval;
- produce clean dated evidence suitable for later retrieval/vector work.

Avoid:

- final priority/signal/actionability/portfolio state in Phase 1;
- raw JSON vector upload;
- hidden paid runs.

## Shared Foundation Rule

If two or more feature workstreams need the same helper, build it as a small
core change first, merge it to `main`, then update the feature branches from
`main`.

Examples of shared foundation:

- path/config/reporting utilities;
- common query/evidence APIs;
- OpenAI/model-resolution helpers;
- record loading/indexing helpers.

Examples of feature-only code:

- MCP tool declarations;
- Custom GPT route/action names;
- Phase-specific prompt assembly.

