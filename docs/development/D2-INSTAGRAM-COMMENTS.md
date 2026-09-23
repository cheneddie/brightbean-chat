# D2 — Instagram Comment Trigger Acceptance

Status: **core implementation already exists upstream; product acceptance strengthened in this fork**

Base: `dev/D1-instagram-oauth`

## Product contract

Instagram comment automation must support:

- all supported posts, including posts published after the automation was authored;
- selected post ids;
- keyword inclusion;
- keyword exclusion;
- unrestricted "Any Comment" when include keywords are blank;
- optional top-level-only filtering;
- self-comment / bot-loop prevention;
- webhook redelivery deduplication;
- durable once-per-comment and optional once-per-person-per-post guards;
- public reply state independent from private reply state;
- comment -> private reply / DM within Meta's allowed window;
- tenant/account isolation.

## Existing implementation verified

### Matching

`apps.flows.triggers.matching._match_comment` already implements:

- `post_scope=all|specific`;
- specific `post_ids`;
- `top_level_only`;
- exclude keywords first;
- include keywords second;
- blank include list -> unconditional match.

Comment keyword lists use contains semantics.

### Instagram normalization

`apps.channels.providers.instagram._comment_event` already:

- requires a stable comment id;
- requires an attributable commenter id;
- maps the media id into the normalized post-id contract;
- preserves parent-comment id when present;
- drops comments authored by the connected Instagram account itself so public auto-replies cannot recursively trigger themselves.

### Idempotency

Existing guards already provide:

- webhook-event dedupe by connection + provider event id;
- handled-comment uniqueness by connection + comment id;
- optional once-per-commenter-per-post database constraint;
- public-reply claim so worker retries do not post a second visible reply;
- one private reply per claimed comment;
- seven-day private-reply eligibility window.

### Existing end-to-end coverage

The upstream Instagram comment suite already covers:

- keyword match -> public reply + private reply;
- duplicate webhook delivery -> no duplicate send;
- once-per-person-per-post;
- disabling once-per-person-per-post;
- no public reply mode;
- random public replies;
- failed public reply does not consume private reply;
- keyword miss;
- top-level-only;
- selected-post scope;
- one-private-reply behavior for multipart flows;
- worker re-run idempotency;
- known and previously unknown commenters.

The inbound parser suite already covers the connected account commenting on its own post/public reply and asserts that it is dropped.

## Fork acceptance added

Added an explicit end-to-end test for our product-level **Any Comment + Any Post** requirement:

- comment trigger has blank `include_keywords`;
- `post_scope=all`;
- webhook names a post id that was never configured in the trigger;
- comment text contains no configured keyword;
- public reply still sends;
- private reply still sends;
- handled-comment row records the new post id.

This locks the intended meaning of "Any Comment" and future posts as a regression test instead of relying only on unit-level matcher behavior.

## D2 conclusion

No second comment engine should be built. Future D2 changes should target only demonstrated gaps in the existing normalized-event -> matcher -> durable guard -> responder pipeline.

## Required before D2 merge

- D0 accepted.
- D1 accepted.
- Fork Actions enabled and CI/security suite green.
- Instagram comment test suite green.
- Webhook signature/dedupe tests green.
- No tenant-isolation regression.
