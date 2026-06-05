# Feeds

Feed modules ingest original material from outside the pipeline.

Current feed families:

- `x/`: X API capture and raw API rebuild.
- `articles/`: saved article/archive ingest.
- `screenshots/`: manual screenshot bundles and reconstruction.

## Contract

Feeds write canonical records and raw supporting material under `<data>/feeds`.
They do not run expensive thread AI and do not push vectors.

Feed modules may:

- fetch or import original material;
- save raw inputs;
- normalize records;
- download/copy local media;
- apply feed-specific reconstruction rules.

Feed modules must not:

- decide final investment meaning with expensive AI;
- write vector memory;
- own presentation rendering;
- hardcode a specific account when config can provide it.
