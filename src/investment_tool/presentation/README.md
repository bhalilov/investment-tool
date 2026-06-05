# Presentation

Presentation modules render local human-readable views.

Current outputs:

- thread HTML pages under `<data>/presentation/threads/x`;
- browse indexes under `<data>/presentation/indexes`.

## Rules

- Presentation output is regenerable.
- JSON records under `<data>/feeds` are more authoritative than HTML.
- Browser-only dynamic decoration, such as owned ticker coloring or relative
  time labels, belongs here.
- Rendering should not mutate feed records except through explicit maintenance
  commands.
