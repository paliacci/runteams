# Employee Chat without a view

Candidate source contract; no production migration or deployment authorized.

The trusted application stages the complete existing composer input, then POSTs
`chats/{chat_id}/employee-messages` with only `operation_key` and `input_ref`.
The cloud resolves the actual global employee Chat, active v4 employee release,
exact product-installation receipt, signed executable and current rental grant.
No caller-selected employee, installation, release, data objects or UI state is
accepted. No UI session is opened. Pending view drafts still block submission.

Snapshot v4 explicitly has `context_mode: employee`, null view/input/context/focus,
empty selection/objects and revision zero. Author-declared employee operations
use the existing signed Wasm executor and SDK. Arbitrary object reads remain
unavailable: operations must perform their declared queries and revision checks.

The existing protected message, dispatch claim, runtime observation and operation
receipt ledgers remain authoritative. GET on the same employee-message endpoint
with the original key only recovers a prior message, never creates or dispatches.
An uncertain POST preserves its key; host/account changes after commit remain
unknown. Current installation/release/employee/chat authorization is repeated
when reading, claiming and invoking. Active-view sends retain the native fence.

## Persisted-message recovery

`GET chats/{chat_id}/recovery` discovers only the last actual protected user
message in the current business epoch. The application owner pins the actor,
workspace and host; cloud checks repeat the current Chat, installation, employee
release and grant authority. The route has no caller-selected message/turn IDs
and never creates a snapshot, message, response, runtime observation or claim.

`not_claimed` permits a visible user action to continue the exact persisted
message through the existing single claim. `unknown` permits only original
receipt reads. Terminal states require the actual saved reply and its existing
hash/provenance checks. A new process, elapsed time or cache never grants another
launch. New composer staging and prepared-message consumption reject while a
claim in the same Chat remains unresolved; original receipt replays remain
readable. Ordinary chats without creator provenance need no creator owner.

This is persisted-message recovery, not recovery of an unconsumed staged input
or an unknown view opening. A claim without an authoritative terminal response
stays unknown; provider reconciliation is separate unfinished work.
