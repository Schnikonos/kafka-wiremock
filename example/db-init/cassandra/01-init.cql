-- Cassandra initialisation for kafka-wiremock examples.
-- Executed by the cassandra-init service via cqlsh once the cluster is ready.
-- NOTE: CQL does not support NOT NULL constraints (only PRIMARY KEY is implicitly non-null).

-- ──────────────────────────────────────────────────────────────────────────────
-- Keyspace
-- ──────────────────────────────────────────────────────────────────────────────
CREATE KEYSPACE IF NOT EXISTS mykeyspace
  WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1}
  AND durable_writes = true;

USE mykeyspace;

-- ──────────────────────────────────────────────────────────────────────────────
-- events table  (generic append-only event store)
-- ──────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS events (
    id         UUID      PRIMARY KEY,
    order_id   TEXT,
    event_type TEXT,
    payload    TEXT,
    created_at TIMESTAMP
);

-- ──────────────────────────────────────────────────────────────────────────────
-- products / orders tables  (Cassandra variant — use UUIDs, no auto-increment)
-- ──────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS products (
    id         UUID      PRIMARY KEY,
    name       TEXT,
    price      DECIMAL,
    created_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS orders (
    id         UUID      PRIMARY KEY,
    product_id UUID,
    status     TEXT,
    created_at TIMESTAMP
);
