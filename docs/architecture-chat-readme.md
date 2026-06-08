# Architecture Chat README

This worktree is for high-level architecture and documentation.

## Start Here

Read:

```text
../HANDOFF.md
README.md
docs/architecture-overview.md
docs/workstreams.md
docs/code-organization-spec.md
docs/pipeline-orchestrator-plan.md
docs/ai-vector-pass-design.md
docs/backlog.md
```

## Rules For This Worktree

- Prefer specs, diagrams, and backlog refinement over production code edits.
- Keep docs implementation-ready: an implementation chat should not need to
  rediscover the same decisions.
- Mark draft/proposal docs clearly.
- If a design decision changes code behavior, update the relevant source-of-
  truth spec and call out implementation impact.
- Do not run paid AI, X API, market data, or vector jobs from this worktree.

## Good Outputs

- architecture overviews;
- workstream plans;
- feature implementation specs;
- cleanup plans;
- explicit decisions and open questions;
- updated backlog items.

## Bad Outputs

- vague essays with no implementation consequence;
- stale specs that contradict code;
- hidden production code changes;
- speculative API contracts presented as final.

