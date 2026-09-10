# RunTeams mobile command v1

This protocol carries a small allowlisted control request from an authenticated iOS/iPadOS device to one desktop host. The account relay is an opaque mailbox: only the desktop can decrypt the command, and only the originating App can decrypt the result.

## Keys and authorization

- The existing random 256-bit host snapshot key encrypts both commands and results with AES-256-GCM.
- Every mobile device owns a separate P-256 Signing key pair. The private key and monotonic command sequence remain in iOS Keychain; the account device record contains only the X9.63 public key.
- A Supabase account session may enqueue/query commands only for its own active Device ID and same-account host. A host writer token may claim/complete commands only for that host.
- The relay never authorizes a business action. The desktop revalidates the decrypted target and action against its current local state immediately before execution.

## Command envelope

The App creates a random 256-bit `command_id`, advances its durable `sequence`, and uses a 30-second lifetime. The relay accepts no lifetime above five minutes.

Clear routing/authentication fields are `command_version`, `algorithm`, `command_id`, `host_id`, `device_id`, `sequence`, `issued_at`, `expires_at`, `nonce`, `ciphertext` and `signature`. `algorithm` is `AES-256-GCM+P256-SHA256`; binary values use unpadded base64url.

The AES-GCM additional authenticated data is:

```text
runteams-mobile-command-v1|{command_id}|{host_id}|{device_id}|{sequence}|{issued_at}|{expires_at}
```

The device signs the following bytes with P-256 ECDSA SHA-256, encoding the signature as DER:

```text
{AAD}|{nonce_base64url}|{ciphertext_base64url}
```

The encrypted JSON payload contains only:

```json
{
  "schema_version": 1,
  "action": "intervention.perform | run.control | document.read",
  "target_id": "workflow:<id>, automation-intervention:<run-id> or artifact:<id>",
  "action_id": "current allowlisted action",
  "response": "optional text"
}
```

`run.control` accepts only `cancel` for a current `workflow:<id>`. Intervention action IDs must still be present on the latest derived core workflow or automation intervention when executed. Legacy Worker, Card, RunChain and numeric intervention IDs are invalid targets.

`document.read` targets `artifact:<id>` so a human can read what they are approving. Document bodies are never part of the snapshot: the desktop returns the text only inside this command's encrypted receipt, capped at 60000 characters (`truncated` marks the cut), and refuses any file type that is not plain text. It never exposes workspace paths, storage keys or digests.

## Replay and stale-state protection

The desktop rejects an invalid signature, altered ciphertext, wrong Host ID, future/expired timestamp, excessive lifetime, unsupported payload or unavailable current action. A durable local receipt ledger has unique constraints for `command_id` and `(device_id, sequence)`; a lower/reused sequence cannot execute again. The backend also enforces unique command IDs and device sequences.

Before any network upload, the desktop persists the encrypted result in a local outbox. Failed uploads are retried independently of command execution; after restart the outbox is drained before new commands are claimed. If delivery is retried after execution, the desktop returns the persisted result without invoking the action again. A claimed command may submit its result during a bounded ten-minute grace period, while an unclaimed expired command remains permanently non-executable.

Command pickup and result waiting use bounded HTTPS long polls. PostgreSQL `LISTEN/NOTIFY` is only a low-latency wake signal: command rows and encrypted result rows remain authoritative. Every reconnect queries durable state before waiting, so a dropped notification, backend restart or temporary listener outage cannot lose a command or cause a second execution. When the notification connection is unavailable the backend temporarily falls back to bounded database checks.

## Encrypted result

The desktop returns `command_id`, `host_id`, `device_id`, `status`, `algorithm`, `completed_at`, `nonce` and `ciphertext`; `algorithm` is `AES-256-GCM`. The result AAD is:

```text
runteams-mobile-command-result-v1|{command_id}|{host_id}|{device_id}|{status}|{completed_at}
```

The encrypted result JSON contains `ok`, a user-facing `message`, and optionally `run_id`. The App shows success immediately after it authenticates and decrypts a `succeeded` result; refreshing the latest encrypted dashboard then runs in the background. Relay failure, host offline state or stale snapshot disables control without interrupting local desktop execution.
