---
name: postgres
description: Query the connected PostgreSQL database using mcp_postgres_query. Use for data lookup, analytics, schema inspection, and any SQL-based questions.
always: false
---

# PostgreSQL Database Access

Use `mcp_postgres_query` to run read-only SQL queries against the connected PostgreSQL database.

## Important Constraints

- **Read-only only.** All queries run inside a `READ ONLY` transaction. `INSERT`, `UPDATE`, `DELETE`, `DROP`, and DDL statements will fail.
- **One tool, one parameter.** The only tool is `mcp_postgres_query(sql: str)`. Pass the full SQL string.
- **No connection management needed.** The MCP server is already connected at startup.

---

## Workflow

### Step 1 — Discover what databases/schemas are available

```sql
-- List all schemas in the current database
SELECT schema_name
FROM information_schema.schemata
ORDER BY schema_name;
```

### Step 2 — List tables in a schema

```sql
-- List all tables in the public schema
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_type = 'BASE TABLE'
ORDER BY table_name;
```

### Step 3 — Inspect a table's columns

```sql
-- Get columns, types, and nullability for a specific table
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'your_table_name'
ORDER BY ordinal_position;
```

### Step 4 — Explore relationships (foreign keys)

```sql
-- Find foreign keys for a table
SELECT
    kcu.column_name,
    ccu.table_name  AS foreign_table,
    ccu.column_name AS foreign_column
FROM information_schema.table_constraints AS tc
JOIN information_schema.key_column_usage AS kcu
    ON tc.constraint_name = kcu.constraint_name
JOIN information_schema.constraint_column_usage AS ccu
    ON ccu.constraint_name = tc.constraint_name
WHERE tc.constraint_type = 'FOREIGN KEY'
  AND tc.table_name = 'your_table_name';
```

### Step 5 — Run a data query

```sql
-- Always use LIMIT when exploring unknown table sizes
SELECT * FROM your_table LIMIT 20;

-- Count rows
SELECT COUNT(*) FROM your_table;

-- Filter, aggregate
SELECT date_trunc('day', created_at) AS day, COUNT(*) AS total
FROM your_table
WHERE created_at >= NOW() - INTERVAL '7 days'
GROUP BY 1
ORDER BY 1 DESC;
```

---

## Schema Inspection Cheatsheet

| Goal | SQL |
|------|-----|
| List all tables | `SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'` |
| Describe a table | `SELECT column_name, data_type FROM information_schema.columns WHERE table_name='x' ORDER BY ordinal_position` |
| List indexes | `SELECT indexname, indexdef FROM pg_indexes WHERE tablename='x'` |
| Show row count | `SELECT COUNT(*) FROM x` |
| Preview data | `SELECT * FROM x LIMIT 10` |
| List enums | `SELECT typname, enumlabel FROM pg_enum JOIN pg_type ON pg_type.oid = pg_enum.enumtypid ORDER BY typname, enumsortorder` |

---

## Best Practices

- **Always LIMIT** when you don't know the row count: `SELECT * FROM x LIMIT 50`
- **Use COUNT first** before fetching large result sets
- **Use `information_schema`** for schema discovery — it works on any PostgreSQL database
- **Use `pg_catalog`** for lower-level introspection (indexes, sequences, enums)
- If the user asks a question and you're unsure of the table name, **discover schema first** (Step 1–2), then query
- Prefer `NOW() - INTERVAL '...'` over hardcoded dates for time-range queries
- Use `ILIKE` for case-insensitive text search: `WHERE name ILIKE '%keyword%'`

---

## Common Patterns

### Recent records
```sql
SELECT * FROM your_table
ORDER BY created_at DESC
LIMIT 20;
```

### Aggregation by time period
```sql
SELECT date_trunc('hour', created_at) AS period, COUNT(*) AS count
FROM your_table
WHERE created_at >= NOW() - INTERVAL '24 hours'
GROUP BY 1
ORDER BY 1;
```

### Search by value
```sql
SELECT * FROM your_table
WHERE some_column ILIKE '%search_term%'
LIMIT 20;
```

### Join two tables
```sql
SELECT a.id, a.name, b.status
FROM table_a a
JOIN table_b b ON b.a_id = a.id
WHERE b.status = 'active'
LIMIT 20;
```

### Check for nulls / data quality
```sql
SELECT
    COUNT(*) AS total,
    COUNT(some_column) AS non_null,
    COUNT(*) - COUNT(some_column) AS null_count
FROM your_table;
```
