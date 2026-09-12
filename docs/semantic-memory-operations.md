# Semantic-memory operations checklist

## Health

- `nanobot-memory status` returns item count and timestamps.
- PostgreSQL listens only on the private address.
- `pg_hba.conf` and the host firewall restrict the application role to Nanobot.
- Connections require TLS.

## Backup

Recommended nightly command:

```bash
pg_dump --format=custom --compress=9 --file=nanobot-$(date -u +%Y%m%dT%H%M%SZ).dump nanobot
```

Retain at least 14 daily copies and keep an additional copy outside the database
container. Validate backups with `pg_restore --list`, and periodically restore to
a temporary database and query `nanobot_memory.items`.

## Failure behavior

A PostgreSQL outage, model-load error, timeout, or incompatible collection disables
semantic recall temporarily. It does not stop normal responses, file-backed memory,
archiving, or Dream. The service retries after the configured backoff.

## Model changes

Do not mix dimensions. The bundled schema is fixed at 384 dimensions. Before
changing to another embedding model, purge/rebuild the derived index or introduce a
new schema migration and collection.
