# Measured model input and context pressure

Context compaction remains owned by the Runner's context governor. Usage shown
for a whole turn (`_last_usage`) can include several requests and is not a
measurement of the next prompt.

For OpenAI-compatible **Chat Completions** requests, the leaf provider records
fingerprints of the actual sanitized messages and request options alongside its
reported input count. Before a later request, the governor may reuse that count
only if the same provider instance, model, tools, options, and complete measured
message prefix still match. An exact match uses the reported count; an append
uses it as a floor under the local estimate. This prevents an underestimated
tokenizer from forgetting known context pressure immediately after a tool reply.

The measurement is a single reported input count, not output tokens, estimated
usage, a retry/turn sum, or another model's usage. A fallback response retains its
actual leaf identity; it is never relabelled as the primary provider. Rewrites,
tool changes, local or native compaction, and unproven routes invalidate reuse.
If fitting cannot remove a known-overbudget prefix and no compactor is available,
the request fails locally instead of resending the known-overbudget input.

Live sessions carry the small fingerprint receipt across runner turns. It is
advisory in-memory state: it is not serialized into session files, checkpoints,
display transcripts, or usage reports. Restart, cache eviction, provider rebuild,
or session clear requires a fresh measurement. Any changed runtime-context prefix
also falls back to ordinary estimation rather than guessing equivalence.

Responses/native continuation retains its provider-state context accounting.
Providers without an explicit input fingerprint contract do not reuse stateless
usage. This is not a promise that all provider routes or remote tokenizers can be
measured before a call, or that the size of newly appended content is exact.

Local fallback estimation uses tiktoken's known model mapping, including
`o200k_base` for GPT-4.1. Unknown models retain the existing `cl100k_base`
approximation, not a claim of native tokenizer accuracy. Tool token caches are
separated by encoding. No configuration or persisted data migration is required.
