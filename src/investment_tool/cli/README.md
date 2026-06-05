# CLI

Command entrypoints live here.

`main.py` is the public command router for installed use. It loads `.env`, then
routes to either workflow commands or storage maintenance.

`legacy_x_capture.py` preserves old X-capture imports and command behavior
during the refactor. It should stay thin: forward to `feeds.x` modules rather
than adding new behavior.

## Rules

- CLI modules parse arguments and dispatch.
- Do not put capture/rebuild/render logic here.
- New production work should enter through `investment-tool workflow ...`.
