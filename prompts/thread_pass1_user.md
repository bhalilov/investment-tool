Analyze the provided thread as a first-pass evidence extraction.

Inputs:
- Source profile: {{source_profile}}
- Thread reconstruction rules: {{thread_rules}}
- Media rules: {{media_rules}}
- Thread JSON: {{thread_json}}
- Media descriptions: {{media_descriptions}}
- Retrieved context: {{retrieved_context}}
- Market price context: {{market_prices}}

Tasks:
1. Extract source-authored factual claims and predictions.
2. Extract user questions the source answered, including parent question context.
3. Extract portfolio/action language as vague evidence only.
4. Extract candidate timeline events with dates when possible.
5. Mark sarcasm, dismissal, irritation, vagueness, secrecy, or manipulation risks when relevant.
6. Mark linked context needed, including other posts or web/articles.
7. Preserve uncertainty and do not force final categories.

Forbidden:
- No final priority.
- No final signal.
- No final actionability score.
- No final portfolio reconstruction.
