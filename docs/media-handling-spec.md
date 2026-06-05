# Media Handling Spec

This spec records current media behavior.

## Ownership

Each X thread stores only thread-local media:

- `media` contains only media keys referenced by tweets in that thread.
- `media_paths` contains only local paths for media keys referenced by tweets in
  that thread.
- A media-free thread must have empty `media` and `media_paths`.

## Download Rules

Configured media rules live in `config/rules/media.default.json`.

Current behavior:

- Download type: `photo`.
- Send-to-AI type: `photo`.
- Placeholder-only types: `video`, `animated_gif`.
- Missing media policy: record a placeholder.

Videos and animated GIFs are recorded as present but are not downloaded and are
not sent to media analysis.

## Missing Media Recovery

Recovery mode may call X only for tweets whose referenced media key has no raw
media metadata. Recovery downloads recovered photos only. Non-photo recovered
metadata remains placeholder-only.

## Media Descriptions

Media description reads downloaded image files and writes one JSON record per
media key under runtime `context/descriptions/x`.

Current fields include:

- media key and path;
- file metadata and hash;
- feed identity;
- model;
- `analysis_stage = media_visual_observation`;
- `ocr_or_description_only = true`;
- model analysis payload.

Media description is visual extraction only. It must not infer trading action or
feed-account intent.
