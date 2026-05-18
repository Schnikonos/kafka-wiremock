#!/bin/bash
# Cassandra initialisation script for kafka-wiremock.
# Executed by the cassandra-init service after the cluster is healthy.
# Uses AllowAllAuthenticator (no credentials) — suitable for local dev.
set -e

CQLSH="cqlsh cassandra-db"

echo "=== Cassandra init: creating keyspace and tables ==="
$CQLSH -f /init/01-init.cql

echo "=== Cassandra init: complete ==="
