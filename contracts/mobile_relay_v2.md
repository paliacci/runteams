# RunTeams account device relay v2

The relay is an optional, ciphertext-only mailbox between RunTeams desktop hosts and iOS/iPadOS devices. Devices using the same authenticated account associate automatically; there is no user-visible pairing step.

## Trust boundary

The relay may persist only random Host/Device/Command IDs, account ownership, host writer-token hashes, mobile P-256 public keys, per-device wrapped host keys, encrypted snapshot/command/result envelopes, APNs routing identifiers, opaque push events, monotonic command sequence numbers and operational timestamps. It must not receive an iOS private key, plaintext host snapshot key, command/result plaintext, pipeline/card plaintext, prompts, transcripts, workspace paths, code, artifacts or Agent Runtime credentials.

An authenticated account session is the authorization boundary. A compromised account session can register a new public key, which an online desktop will trust as an account device.

## Key hierarchy

- Each host creates one random 256-bit snapshot key and encrypts its allowlisted mobile projection with AES-256-GCM.
- Each mobile device creates a P-256 Key Agreement key pair; the private key remains in Keychain.
- For every account device, the host performs ephemeral P-256 ECDH and HKDF-SHA256 (`salt = host_id`, `info = runteams-host-key-wrap-v1`), then wraps the host snapshot key with AES-256-GCM.
- Snapshot AAD: `runteams-host-envelope-v1|{host_id}|{schema_version}|{snapshot_version}`.
- Wrapped-key AAD: `runteams-host-key-wrap-v1|{host_id}|{device_id}`.

## Account-device endpoints

- `PUT /v1/mobile/account-devices/{device_id}` — Supabase bearer token; register Device ID plus P-256 Key Agreement and Signing X9.63 public keys.
- `DELETE /v1/mobile/account-devices/{device_id}` — Supabase bearer token; revoke the device and delete its wrapped keys/APNs registration.
- `PUT|DELETE /v1/mobile/account-devices/{device_id}/push-token` — Supabase bearer token; register or remove this account device's APNs route.
- `GET /v1/mobile/hosts?device_id=...` — Supabase bearer token; return same-account hosts that have wrapped a key for this device, including the host's plaintext-free `last_seen_at` presence timestamp.
- `GET /v1/mobile/hosts/{host_id}/snapshot?device_id=...` — Supabase bearer token; return the opaque host envelope with `ETag`/`304` support.
- `POST /v1/mobile/hosts/{host_id}/commands` — Supabase bearer token; enqueue a same-account, device-signed opaque command envelope.
- `GET /v1/mobile/hosts/{host_id}/commands/{command_id}?device_id=...` — Supabase bearer token; return opaque command status and encrypted result when complete.

## Host endpoints

- `POST /v1/relay/hosts` — Supabase bearer token; idempotently bind Host ID and writer-token hash to the account.
- `GET /v1/relay/hosts/{host_id}/mobile-devices` — host writer token; list active same-account Device IDs/public keys and whether a wrapped key exists.
- `PUT /v1/relay/hosts/{host_id}/mobile-devices/{device_id}/key` — host writer token; upload one wrapped host key.
- `PUT /v1/relay/hosts/{host_id}/snapshot` — host writer token; upload one monotonic opaque snapshot envelope.
- `POST /v1/relay/hosts/{host_id}/push-events` — host writer token; fan out a generic, idempotent event to all active account-device APNs registrations.
- `GET /v1/relay/hosts/{host_id}/commands` — host writer token; atomically claim queued opaque commands for this host.
- `PUT /v1/relay/hosts/{host_id}/commands/{command_id}/result` — host writer token; complete a claimed command with an encrypted desktop receipt.

APNs alerts remain plain system notifications with no actionable category. For precise navigation they may include the random Host ID and `target_ref = SHA256(host_id | kind | local_object_id)`. After decrypting the latest host snapshot, iOS recomputes candidate references locally and opens the matching intervention or run. The relay and APNs never receive the plaintext local object ID, pipeline/card title or work record.

Notification routing is not a remote mutation protocol. Direct approval, rejection, retry, terminate, text response and run pause/resume/cancel use the encrypted, auditable and replay-protected protocol in `mobile_command_v1.md`. Live Activities, if enabled later, use that same command boundary rather than ordinary notification actions.

QR/token pairing has been removed. Account association is the only supported device-discovery path.

Host registration refreshes `last_seen_at` even when the encrypted projection is unchanged. Mobile clients use that heartbeat—not snapshot generation time—to infer presence, and mark a host offline after 90 seconds while retaining its last decrypted snapshot.
