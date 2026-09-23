# D5 — Instagram Rich-message Rendering

Status: **implementation under CI validation**

Tracking issue: `#13`

## Product contract

Canonical outbound content for Instagram must cover:

- text
- image
- video
- standalone link
- button
- quick reply
- card/gallery where supported

Flows author abstract content. The shared rendering/downgrade layer and Instagram adapter decide the provider payload.

## Changes

### Canonical standalone link

Added `LinkBlock(url, label)` to the channel event vocabulary.

It:
- persists in `Message.body` as `{"type":"link","url":...,"label":...}`;
- round-trips through retry reconstruction;
- can be authored by a `send_message` flow block;
- is present in the flow schema tagged union;
- downgrades losslessly to text:
  - with label: `Label: URL`
  - without label: `URL`

The downgrade is deliberately shared rather than Instagram-specific, because no provider needs a fake native "link block" primitive to deliver a clickable URL.

### Fail-visible controls

Instagram previously could render a media-only message and silently omit authored buttons or quick replies because Meta requires:
- buttons to live on a generic-template element;
- quick replies to live beside text.

D5 now verifies the final wire payload before any provider call. If authored controls disappeared, the whole send fails with:

`controls_unrenderable`

No partial provider send is made.

## Existing Instagram rendering retained

- text splitting by Meta byte cap;
- image/video attachment payloads;
- media captions as following text bubble;
- URL buttons -> `web_url`;
- postback buttons -> `node_id:button_id`;
- quick replies -> payload carrying `node_id:reply_id`;
- cards/galleries -> generic templates;
- unsupported file media -> safe text/link downgrade.

## QA added

- standalone LinkBlock persistence/retry round trip;
- labelled/unlabelled link downgrade;
- standard send-message fixture contains a canonical link;
- standalone link reaches Instagram as clickable text;
- media-only button send fails before any provider call;
- media-only quick reply send fails before any provider call.

## Merge gate

- generated/static flow schema agrees with server schema;
- Ruff green;
- mypy/TypeScript green;
- pytest green;
- gitleaks green;
- dependency audit/frontend deterministic build green;
- Docker production smoke green.
