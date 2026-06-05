# Screenshot Source Spec

This spec records current manual screenshot behavior.

## Purpose

Manual screenshots are source records for X threads that may not be available
through the X API. A screenshot set may contain multiple threads, overlapping
scroll positions, and screenshots embedded inside visible posts.

## Bundle Import

Current import behavior:

- accepts explicit screenshot file paths;
- supports jpg, jpeg, png, and webp;
- copies screenshots into runtime `sources/screenshots/media/<bundle_id>`;
- writes one bundle JSON under runtime `sources/screenshots/bundles`;
- records dimensions, hash, original filename, imported path, and duplicate
  relationships.

## Reconstruction

When AI reconstruction is requested:

- group screenshots into scroll/thread groups using overlaps, repeated posts,
  reply-chain structure, timestamps, and root hints;
- create separate reconstructed threads when roots or contexts differ;
- merge duplicate/overlapping visible posts;
- preserve only visible text;
- mark `starts_cut_off` and `ends_cut_off` when text is cut off;
- describe embedded media visible inside posts;
- keep screenshot indexes as evidence references.

The reconstruction pass must not infer investment signal, priority, portfolio
action, or correctness.

## Target Workflow

The future `screenshots` stage should scan a flat inbox and run grouping and
reconstruction as part of scheduled update.
