# Feed Record Spec

This spec records the current stored-record behavior. Feed records are local evidence files. They are not final AI
analysis and should remain usable without vector storage.

## X Thread Records

Clean X records live under runtime `feeds/x/records`.

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
- `feed`

Feed capture fields:

- `tweets`
- `users`
- `media`
- `media_paths`
- `non_photo_media`
- `rate_limits`
- `completeness_status`
- `source_completeness`
- `analysis_stage`

Rules:

- `feed` must include feed id, platform, module, username, user id, display
  name, and whether raw API/X API was used.
- X records may include `preview_text` before thread AI runs.
- X records must not contain final AI fields unless `analysis` is present and
  `analysis_stage` is no longer pending.
- `completeness_status` is source completeness only, not AI confidence. Current
  values include `conversation_search_exhausted`,
  `conversation_search_limited`, `api_partial_missing_references`, and
  `not_searched_cached`.
- `source_completeness` should explain the status with root presence,
  missing reference ids, and conversation-search page counts when available.
- Ignored X records move to runtime `feeds/x/ignored` and include
  `ignored`, `ignored_reason`, and `ignored_at`.

## Article Records

Saved article records live under runtime `feeds/articles/records` for the
configured archive feed.

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
- `feed`
- `captured_by`
- `updated_at`
- `ocr_used`

Rules:

- Article ingest uses saved HTML text and image alt text only.
- Article ingest does not OCR images.
- `fingerprint` prevents unnecessary AI reruns.

## Screenshot Bundle Records

Manual screenshot records live under runtime `feeds/screenshots/bundles`.

Current fields:

- `bundle_id`
- `bundle_name`
- `feed_type`
- `feed`
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
