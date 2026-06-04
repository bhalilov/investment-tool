# Source Record Spec

This spec records the current stored-record behavior before the package
refactor. Source records are local evidence files. They are not final AI
analysis and should remain usable without vector storage.

## X Thread Records

Clean X records live under runtime `x_threads/thread_json`.

Required identity and routing fields:

- `conversation_id`
- `title`
- `canonical_filename`
- `canonical_json_filename`
- `created_at`
- `captured_at`
- `type`
- `primary_label`
- `tickers`
- `tags`
- `source`

Source capture fields:

- `tweets`
- `users`
- `media`
- `media_paths`
- `non_photo_media`
- `rate_limits`
- `completeness_status`
- `analysis_stage`

Rules:

- `source` must include source id, platform, module, username, user id, display
  name, and whether raw API/X API was used.
- X records may include `preview_text` before thread AI runs.
- X records must not contain final AI fields unless `analysis` is present and
  `analysis_stage` is no longer pending.
- Ignored X records move to runtime `x_threads/ignored` and include
  `ignored`, `ignored_reason`, and `ignored_at`.

## Article Records

Saved article records live under runtime `hardcore/article_json` for the current
configured archive source.

Current fields:

- `article_id`
- `index`
- `title`
- `url`
- `date`
- `date_iso`
- `html_path`
- `pdf_path`
- `text`
- `html_meta`
- `analysis`
- `fingerprint`
- `source`
- `captured_by`
- `updated_at`
- `ocr_used`

Rules:

- Article ingest uses saved HTML text and image alt text only.
- Article ingest does not OCR images.
- `fingerprint` prevents unnecessary AI reruns.

## Screenshot Bundle Records

Manual screenshot records live under runtime `manual_threads/bundles`.

Current fields:

- `bundle_id`
- `bundle_name`
- `source_type`
- `source`
- `created_at`
- `analysis_stage`
- `status`
- `screenshots`
- `stitch_groups`
- `reconstructed_threads`
- `reconstruction`
- `notes`

Rules:

- Each screenshot records original path, imported path, file metadata,
  dimensions, hash, and embedded datetime if discoverable.
- Duplicate screenshots are recorded with `duplicate_of_index`.
- AI reconstruction output is stored in `reconstruction`, `stitch_groups`, and
  `reconstructed_threads`.
