# D7 — Visual Flow Builder Integration

Status: implementation complete; awaiting final CI/merge.

Tracking issue: `#17`
Pull request: `#18`

## Roadmap contract

The Visual Builder must expose the Instagram-first automation primitives required to assemble:

`Comment -> Public Reply -> Opening DM -> Follow Check -> Content / Follow Prompt`

Required builder capabilities:

- Instagram comment trigger;
- public reply configuration;
- send message/media;
- Instagram follow-status condition;
- tag add/remove;
- custom-field condition/action;
- delay/wait;
- branching and terminal/end semantics;
- human handoff.

## What D7 adds

### First-class human handoff

`human_handoff` is now a terminal flow node.

It:

- requires a channel connection;
- opens/reopens the contact's conversation;
- optionally assigns it to a member of the same workspace;
- ends the current flow successfully;
- exposes no outgoing handles.

Long-lived inbox takeover/resume policy remains D8 scope.

### Follow-gate builder integration

The Builder exposes the native three-state Follow Gate:

- `follow:following`;
- `follow:not_following`;
- `follow:unknown`.

The canvas shows human-readable branch labels and a compact policy preview.

### Opinionated Instagram template

`flow-templates/instagram-comment-follow-to-unlock.json` implements the product path:

1. Instagram comment trigger with public reply;
2. one opening DM;
3. user interaction before the follow check;
4. native Instagram Follow Gate;
5. FOLLOWING -> protected content;
6. NOT_FOLLOWING -> follow prompt + retry;
7. UNKNOWN -> explicit retry path;
8. follower tag action after successful delivery.

The opening DM intentionally waits for a user tap before checking follow status so the normal DM window is opened by a real interaction rather than by chaining a second message onto the one-time comment private reply.

### Builder registry / UI

- human handoff is present in the server schema and generated static schema;
- builder handle grammar includes all Follow Gate branches;
- node previews include Follow Gate and human handoff;
- human handoff is terminal in both server and frontend semantics;
- template generation understands first-class handoff.

## Acceptance coverage

D7 tests lock:

- the full roadmap capability list;
- native Follow Gate branch handles;
- tag/custom-field action verbs;
- smart-delay availability;
- terminal handoff semantics;
- the complete follow-to-unlock template path;
- canonical frontend graph serialization with the new terminal node.

## D8 boundary

D7 only expresses and executes the handoff point in a flow.

D8 owns:

- human takeover/resume policy;
- richer inbox workflow;
- conversation assignment lifecycle;
- CRM/inbox operational behavior.
