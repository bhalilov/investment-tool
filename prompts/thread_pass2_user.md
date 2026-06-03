Analyze the provided thread using full retrieved context.

Inputs:
- Source profile: {{source_profile}}
- Current thread first-pass evidence: {{thread_pass1}}
- Retrieved prior evidence: {{retrieved_context}}
- Market prices: {{market_prices}}
- Static article context: {{static_context}}
- Human corrections: {{human_corrections}}

Tasks:
1. Resolve likely intended meaning where context supports it.
2. Validate or reject candidate timeline events.
3. Identify contradictions, stale references, missing context, or sarcasm traps.
4. Produce final categorized evidence only when sufficiently supported.
5. Preserve ambiguity when context is still insufficient.
