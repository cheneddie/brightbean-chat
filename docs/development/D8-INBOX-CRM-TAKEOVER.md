# D8 — Inbox / CRM Human Takeover Lifecycle

Status: source implementation complete; executable validation pending.

Tracking issue: `#19`.

## Existing D8 baseline retained

BrightBean already had the CRM/inbox foundations required by the Instagram-first roadmap:

- stable channel identity via `ContactChannelIdentity`;
  - connected identities are unique by `(channel_connection, platform_user_id)`;
  - pending identities are unique by `(workspace, platform, platform_user_id)`;
  - usernames/profile metadata are not identity keys;
- durable `Conversation` + `Message` history;
- contact tags and typed custom fields;
- source attribution through message `source`, consent `opt_in_source`, and automation execution metadata;
- inbox assignment, open/done controls, pause/resume, and stop-automation controls;
- inbound routing already suppresses trigger/resume stages while a conversation pause is active.

D8 does not rebuild those systems.

## Gap 1 — scheduled execution resume during human takeover

Before D8, webhook routing respected `conversation.automation_paused_until`, but queue-driven execution resumes did not.

A Smart Delay or follow-up timer that became due while an agent was handling the conversation could advance the flow anyway.

D8 changes the queue resume path:

1. re-resolve the exact tenant-scoped flow execution;
2. reject vanished/non-live/stale-token actions normally;
3. read the conversation for the execution's contact + channel connection;
4. if human takeover is active, do not advance the flow;
5. schedule one idempotent successor at the pause boundary;
6. let the original queue row finish successfully rather than spending retry/backoff budget.

A successor carries `_takeover_deferred=true` only as an internal queue marker.

If the pause is extended, the successor defers again to the new boundary.

If an operator explicitly resumes automation, pending takeover-deferred flow timers for that contact are moved to `run_at=now` under the same contact lock, so eligibility returns immediately.

Stale timers never get churned merely because a pause is active.

## Gap 2 — durable conversation ownership audit

D8 adds `ConversationAudit`, scoped to the conversation's workspace.

Recorded events:

- assigned;
- unassigned;
- automation paused;
- automation resumed;
- conversation reopened;
- conversation marked done;
- system human handoff.

Each row records:

- conversation;
- structured event;
- human/system source;
- actor when a workspace member performed the change;
- a bounded actor display-name snapshot so the event stays attributable after account deletion/rename;
- structured internal metadata used for ownership/debug context;
- timestamps.

The audit never stores message bodies.

Human actor and assignee ids are validated against membership in the conversation's workspace before mutation.

## Agent takeover semantics

An Inbox reply or internal note establishes takeover before the outbound send:

- acquire the same contact advisory lock used by flow execution;
- extend the pause by `AGENT_AUTOMATION_PAUSE`;
- never shorten a longer manual pause;
- write a human audit event;
- then use the existing messaging send pipeline.

This closes the race where a due flow timer and an agent reply could otherwise pass each other.

## Visual Builder human handoff

D7's `human_handoff` node now enters the full D8 ownership lifecycle:

- open/reopen the inbox conversation;
- optionally assign a member of the same workspace;
- pause automation;
- record a system `human_handoff` audit event;
- end the current flow.

## Inbox audit surface

The sidebar shows the newest ownership/state audit rows using only:

- fixed event labels;
- actor display name or System;
- timestamp.

Arbitrary audit metadata is deliberately not rendered.

## Data lifecycle

`ConversationAudit` is conversation-scoped and cascades with the conversation/contact erasure path.

The existing contact subject-export schema is unchanged because SPEC §19 does not list operator ownership audit as a required exported section.

## D8 acceptance

- webhook trigger/resume respects active pause — existing contract;
- scheduled execution resume respects active pause;
- takeover-delayed timer keeps its wake-up without spending retry budget;
- pause extension re-defers safely;
- explicit resume immediately releases takeover-deferred flow timers;
- stale timers remain stale and are not perpetually deferred;
- human handoff creates a real automation pause;
- assignment/unassignment/pause/resume/open/done are durably audited;
- agent reply establishes an audited takeover pause under the contact lock;
- a longer manual pause is never shortened;
- cross-workspace actor/assignee combinations are refused;
- audit is visible in the inbox sidebar;
- full CI/security suite must be green before merge.
