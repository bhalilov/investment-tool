# Screenshots Feed

This folder handles manually supplied screenshots of threads or thread
fragments.

Manual screenshots exist because some conversations may not be available through
the X API or may need human-provided capture.

## Main Files

| File | Purpose |
| --- | --- |
| `bundles.py` | Import screenshot files into bundles |
| `reconstruct.py` | Prompt helpers for grouping/stitching/reconstruction |

## Rules

- Preserve input order and file metadata.
- Copy screenshots into runtime media storage.
- Mark duplicates and overlap candidates.
- Reconstruction may identify multiple thread groups inside one screenshot set.
- The output should become compatible with normal feed records before later AI
  passes consume it.
