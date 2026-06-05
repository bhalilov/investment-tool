# X Reconstruction Spec

This spec records current X reconstruction behavior.

## Inputs

- Configured X feed profile resolved through `config/feed_modules.json`; the
  current X module points to `config/feeds/x_accounts.json`.
- Thread rules from `config/rules/thread_reconstruction.default.json`.
- Raw X API responses stored under runtime `feeds/x/raw`.
- Existing clean thread JSON used as cache when available.

## Thread Inclusion

Current reconstruction includes:

- root posts authored by the configured feed account;
- feed-authored replies in conversations;
- the parent question when the feed reply answers another user;
- quote posts referenced by feed posts;
- explicit linked X posts found in tweet URLs;
- parent chains up to configured depth.

Current reconstruction excludes:

- random user replies unless they are part of feed reply context;
- off-topic retweets;
- off-topic feed reply contexts;
- self-promo retweets matching configured patterns.

## Conversation Fetching

Live capture:

- fetches the configured feed timeline;
- walks referenced posts and parent chains;
- searches conversations only when the cached thread is missing or changed;
- uses configured `conversation_pages` unless overridden.

Raw rebuild:

- rebuilds generated JSON from saved raw API responses;
- does not call X;
- may stage output before replacing generated JSON.

## Classification

Thread type is feed-configurable:

- feed root post: `FEED_THREAD`
- feed reply context: `FEED_REPLY_CONTEXT`
- linked context: `LINKED_CONTEXT`

Thread relevance is determined from feed-authored text, root text, linked
research domains, media presence, explicit linked posts, and ticker/finance
language.

## Sorting

Thread posts are rendered and processed oldest-first when producing human views.
