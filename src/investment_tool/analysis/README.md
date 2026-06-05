# Analysis

Analysis modules are for shared AI helpers and future expensive AI passes.

Current implemented code:

- `openai.py`: OpenAI request helpers, JSON extraction, and usage metadata.

Future code here should include reusable AI pass mechanics. Feed-specific
capture should not move here, and AI prompts should remain configurable rather
than hardcoded in Python.

## Rules

- Keep AI calls explicit and report usage.
- Do not run paid calls from import-time code.
- Keep pass prompts and model choices in config/prompt files.
- Phase 1 thread AI has no vector search until the AI/vector spec changes.
