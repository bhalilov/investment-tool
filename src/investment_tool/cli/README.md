# CLI

Command entrypoints live here.

`main.py` is the public command router for installed use. It loads `.env`, then
routes to workflow commands.

## Rules

- CLI modules parse arguments and dispatch.
- Do not put capture/rebuild/render logic here.
- New production work should enter through `investment-tool workflow ...`.
