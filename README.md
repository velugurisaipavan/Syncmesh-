# Syncmesh: Distributed Data and Computing

**New paper-aligned Python starter** for *Orchestrating Distributed Data and Computing in Decentralized Environments: A Unified Approach*, Sai Pavan Veluguri.

> This is newly written reconstruction code, not recovered original experimental scripts. No original GCP benchmark, network-traffic reduction, latency result, or production-readiness claim is reproduced. The associated paper PDF is not bundled.

## What is implemented

- Stateless HTTP/GraphQL request orchestration with durable state in MongoDB
- One local data database, one metadata database, and a separate change-stream listener per node
- Multi-node collection and local-first aggregate queries
- Sum-and-count aggregation, correctly weighted across unequal node sizes and missing values
- Manual peer registration, subscription flags, and geographic radius selection
- Local-only create/update/delete GraphQL mutations
- Best-effort direct event replication with origin-qualified replica IDs
- Idempotent/stale-event-safe replica application, versioned delete tombstones, and loop prevention
- Three independent MongoDB replica sets plus three nodes/listeners via Docker Compose
- Optional OpenFaaS HTTP-watchdog image recipe
- Genuine-CSV ingestion and real-request RTT measurement tools
- Software tests, dependency configuration, and GitHub Actions test workflow

## Architecture

```text
Client -> node /request -> local MongoDB (syncmesh.measurements)
                 |
                 +-> known/explicit peers -> local-only query on each peer
                 |
                 +-> collection merge OR weighted summary -> client

Local measurement change -> separate Mongo change-stream listener
                 |
                 +-> subscribed peer /events -> syncmesh.replicas

Peer metadata + listener offsets -> MongoDB syncmesh_meta
```

The request handler keeps no durable application state in process memory. MongoDB collections, peer metadata, replica tombstones, and listener offsets are stateful. Connection pools and HTTP-client configuration are process-local resources, not a consensus mechanism.

## Quick start: three local nodes

Requirements: Docker Engine, Docker Compose v2, and Python 3.10+ for helper scripts/tests. Compose is a **local trusted-development deployment**, not a secure internet-facing deployment.

```bash
python -m venv .venv
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest -q
```

Generate a random shared development token:

```bash
python -c "import secrets,pathlib; pathlib.Path('.env').write_text('SYNCMESH_TOKEN='+secrets.token_hex(32)+'\n')"
```

Start the stack:

```bash
docker compose up --build -d
```

Nodes are available at `http://localhost:8081`, `:8082`, and `:8083`. MongoDB ports are not published. Each node has an independent database volume and independent single-member replica set. Single-member replica sets enable change streams; **they do not provide database high availability**.

Export the same token for Python/curl commands. Bash:

```bash
set -a
. ./.env
set +a
```

PowerShell equivalent:

```powershell
$env:SYNCMESH_TOKEN = (Get-Content .env | Where-Object { $_ -like 'SYNCMESH_TOKEN=*' }) -replace '^SYNCMESH_TOKEN=', ''
```

Register peers:

```bash
python scripts/register_mesh.py
```

Registration sets `subscribed=false`; event replication remains off until explicitly enabled. From your host, use localhost ports. Inside the Docker network, peer identities are `http://node1:8080`, `http://node2:8080`, and `http://node3:8080`. Origin identity must remain stable once data is created. Changing `NODE_URL` changes replica identity and needs a deliberate migration.

Check startup and logs:

```bash
curl http://localhost:8081/healthz
docker compose logs node1 listener1
```

`/healthz` reports process liveness after startup, not a continuously probed database readiness check. Stop with `docker compose down`; remove all persisted records only if intended using `docker compose down -v`.

## Real sensor data

No invented sensor dataset is included. `examples/measurements-template.csv` contains a header only:

```text
sensor_id,timestamp,temperature,humidity,pressure
```

Provide genuine observations with timezone-aware ISO-8601 timestamps, e.g. an explicit `Z` or numeric UTC offset. The API canonicalizes timestamps to UTC. Historical AirSofia-style CSVs may have local timestamps or additional columns: write a source-specific adapter, establish the original timezone, resolve daylight-saving ambiguities, and keep units consistent. This starter does not guess timezone, units, or missing provenance. Supply numeric metrics; empty values are null. IDs are strings.

The uploaded paper references https://airsofia.info/ as its data source, but the exact sensor/date slice and original replay scripts were not supplied. No dataset download, historical benchmark data, or reconstructed cohort is included.

Import to each node separately, using the intended partition for that node:

```bash
python scripts/ingest_csv.py --csv private-data/node1.csv --url http://localhost:8081
python scripts/ingest_csv.py --csv private-data/node2.csv --url http://localhost:8082
python scripts/ingest_csv.py --csv private-data/node3.csv --url http://localhost:8083
```

The ingest tool sends real local GraphQL mutations; it is not a timed sensor replay. Imports assign fresh UUIDs: rerunning imports duplicates records. For controlled experiments, define unique source keys or clear/reset the test dataset deliberately, keep a manifest of input partitions/checksums, and avoid duplicates across authoritative nodes. No privacy or de-identification guarantee is implied.

## Query the mesh

Collect:

```bash
curl -s http://localhost:8081/request \
  -H "Authorization: Bearer $SYNCMESH_TOKEN" \
  -H 'Content-Type: application/json' \
  --data-binary @examples/collect.json
```

Aggregate:

```bash
curl -s http://localhost:8081/request \
  -H "Authorization: Bearer $SYNCMESH_TOKEN" \
  -H 'Content-Type: application/json' \
  --data-binary @examples/aggregate.json
```

The response contains `partial`, `queried_nodes`, and `failed_nodes`. A failed or timed-out peer is skipped without retry; available data returns with `partial=true`. **Do not report that result as a complete global aggregate.** Each selected peer is contacted once, sequentially. A forwarded request sets `local_only=true`, clears the peer list, and disables metadata discovery to prevent recursive fan-out. There is no global node discovery or arbitrary multi-hop graph traversal.

Use `external_nodes` for explicit peers, `use_meta_data=true` for stored peers, and optional `radius` in kilometers. The node itself is always included. Every explicit peer in a radius query needs registered coordinates. Peer selection computes Haversine distance at request time and sorts by distance. This differs from the paper's cached-distance description. Queries only cover registered/explicit one-hop peers, not automatically every node within a geographic area.

### Time/sensor filters

Use GraphQL variables rather than building strings from untrusted input:

```json
{
  "query": "query($filter: MeasurementFilter) { measurements(filter: $filter) { sensor_id timestamp temperature } }",
  "variables": {
    "filter": {
      "sensor_id": "YOUR_REAL_SENSOR_ID",
      "start": "2020-01-01T00:00:00Z",
      "end": "2020-01-02T00:00:00Z"
    }
  },
  "request_type": "collect",
  "use_meta_data": true
}
```

This is an illustrative filter, not supplied sensor observations. `start` is inclusive; `end` is exclusive. Aggregation applies the same filter to each authoritative local dataset. Per-field `sums` and `counts` are combined before calculating means; node means are not averaged naively. Missing values do not count toward that field's denominator. `count` counts records even if a metric is null. Aggregation computes all three configured weather metrics; the GraphQL field selection projects collection responses only.

## Request contract

| Parameter | Purpose |
|---|---|
| `query` | Real GraphQL query or local mutation |
| `variables` | GraphQL variables |
| `database` | Allowlisted `syncmesh` only |
| `collection` | Allowlisted `measurements` only |
| `request_type` | `collect` or `aggregate` |
| `external_nodes` | Explicit static-allowlisted peer origins |
| `use_meta_data` | Include manually stored peers; default true |
| `radius` | Optional geographic radius in kilometers |
| `local_only` | Do not forward to peers |
| `include_replicas` | Local collect inspection only; never aggregate copies |

The GraphQL subset deliberately supports exactly one operation, one root field, variables, aliases, and flat scalar selections. Fragments, directives, introspection, arbitrary Mongo filters, dynamic collection names, and GraphQL subscriptions are not supported. Invalid queries fail clearly; there is no string-matching substitute for GraphQL execution.

A collection over the cap (10,000 records by default) fails rather than silently truncating. Narrow time/sensor filters; a pagination/cursor API is not implemented. A large peer collection may fail that peer's cap and mark the global response partial. Aggregate queries use MongoDB's sum/count pipeline and do not transfer raw measurements between nodes. Finite metric validation is enforced at API boundaries; direct database writes must preserve the same schema.

## Local mutations

```graphql
mutation($input: MeasurementInput!) {
  createMeasurement(input: $input) { id replica_id }
}
```

Also implemented:

```graphql
mutation($id: ID!, $input: MeasurementInput!) {
  updateMeasurement(id: $id, input: $input) { id timestamp }
}
```

```graphql
mutation($id: ID!) {
  deleteMeasurement(id: $id)
}
```

Use returned IDs and real input observations. Updates replace the full measurement. Mutations never forward, even when metadata discovery defaults to true; explicit peers/radius/aggregate requests on a mutation are rejected. There is no remote mutation of replicas and no multi-master conflict resolution.

## Peer metadata and replication

List and register/update peers using the same Bearer token:

```bash
curl -s http://localhost:8081/meta/nodes \
  -H "Authorization: Bearer $SYNCMESH_TOKEN"

curl -s -X PUT http://localhost:8081/meta/nodes \
  -H "Authorization: Bearer $SYNCMESH_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"url":"http://node2:8080","latitude":42.01,"longitude":23.0,"subscribed":true}'
```

These coordinates are local demo configuration, not claimed AirSofia sensor locations. Delete with `DELETE /meta/nodes?url=...`.

Here `subscribed=true` in **node1's metadata entry for node2** means node2 receives future local changes from node1. Each source listener watches only its authoritative `syncmesh.measurements` collection. Received replicas go to a separate `syncmesh.replicas` collection, so they cannot trigger onward replication loops. This is a deliberate hardening change from co-locating copies.

Replica identity is `origin#document_id`, where origin is the stable node URL. Events carry a deterministic event ID and an ordered source-MongoDB `clusterTime` version. Atomic conditional replacement plus a unique `_id` makes duplicate/stale events no-ops. Delete tombstones retain their version to prevent an old update resurrecting a deleted copy. Tombstones are not automatically garbage-collected.

To inspect copies, send a collect request with `local_only=true`, `use_meta_data=false`, and `include_replicas=true`. Regular federation and aggregation query authoritative records only. This avoids double-counting cached replicas, but it also means replicas are **not** an automatic failover source for global reads. A failed owner produces partial results even if some copy exists elsewhere.

### Delivery limitations

The listener is best-effort: it attempts each subscribed peer once, ignores the response content, and records the stream offset after attempts. It is **not** guaranteed-delivery fire-and-forget, exactly-once processing, or durable per-peer delivery. Failed sends are logged and not queued/retried. A listener crash may repeat events; receiver version checks handle repeats. Late subscriptions receive no initial snapshot/backfill. Missed failed deliveries require external reconciliation, which is not implemented.

One listener per node is required: multiple listeners with the same offset are not coordinated. The saved resume token permits reopening while the MongoDB oplog retains the needed history. Expired/invalid tokens need operator intervention; the code does not silently reset and pretend nothing was lost. On first startup without an offset, only changes after opening the stream are observed.

`updateLookup` may return a newer document state or no document if it was deleted before lookup. The listener skips an absent lookup; a later delete can still apply. This is a lightweight latest-state replication aid, not a reliable historical change log or transactional event bus. Original records and replica updates are not in a cross-node transaction; global queries have no consistent multi-node snapshot, linearizability, or consensus guarantee.

## Standalone development

Provide a reachable replica-set MongoDB instance and environment variables:

```bash
export NODE_URL=http://localhost:8080
export MONGO_URI='mongodb://localhost:27017/?replicaSet=rs1'
export PEER_ALLOWLIST='http://localhost:8082,http://localhost:8083'
export NODE_LATITUDE=42.0
export NODE_LONGITUDE=23.0
# SYNCMESH_TOKEN must already contain a random token of at least 32 characters.
python -m uvicorn syncmesh.app:create_app --factory --host 127.0.0.1 --port 8080
```

In a second terminal with the same environment:

```bash
python -m syncmesh.listener
```

A standalone non-replica-set MongoDB server cannot provide change streams. Never assume the single-process unit-test database substitute verifies real MongoDB replica-set behavior.

## Optional OpenFaaS packaging

`deploy/Dockerfile.openfaas` adapts this HTTP application to `of-watchdog` HTTP mode:

```bash
docker build -f deploy/Dockerfile.openfaas \
  --build-arg WATCHDOG_IMAGE=YOUR_REVIEWED_OF_WATCHDOG_IMAGE_AT_DIGEST \
  -t YOUR_REGISTRY/syncmesh:reviewed .
```

Replace the placeholders with actual reviewed images/registry names. Deployment needs platform-specific secrets, network access to each node's MongoDB, and a stable node origin. The code intentionally only permits origin URLs (no `/function/name` path). If using the OpenFaaS gateway, configure a reverse proxy/domain per node to map `/request`, `/events`, `/meta/nodes`, and `/healthz` to the function's gateway prefix. Direct unadapted gateway URLs will not work as peer origins. The listener remains a separate long-lived service, not a short-lived function. Platform deployment, autoscaling, faasd provisioning, Terraform/GCP creation, and this optional image build were not tested here.

## Measurement tools

Run against actual ingested data and a live stack:

```bash
python scripts/benchmark.py --url http://localhost:8081 \
  --request-json examples/aggregate.json --count 20 --warmup 2 \
  --output results/aggregate.csv
```

The script saves one real observation per request: client RTT (milliseconds), HTTP status, decoded response bytes, partial flag, and exception type. A partial result is not a successful complete mesh query; filter/report it separately. `decoded_response_bytes` is **not wire traffic**: it excludes headers, TCP/TLS, compression differences, ingest traffic, replication traffic, and internal peer/MongoDB links. Compression is handled by HTTP clients; decoded byte counts must not be labeled total network flow.

To reproduce a traffic experiment, measure the same ingestion/query interval for every link with an external packet capture, define whether TCP ACKs/retransmissions/TLS are counted, and separately measure host CPU/RAM. For example, adapt `tcpdump` to your actual interface and endpoint/port filter, subject to permissions and data-handling rules. The starter does not automate pcap analysis or produce paper tables.

A local Compose run is not comparable to multi-region GCP experiments. Centralized MongoDB and sharded-MongoDB reference deployments are **not** supplied. No result comparison, percentages, simulated RTTs, fabricated sensor readings, or claimed performance improvements are included. The paper's original dataset partitions, captures, exact request plans, and Terraform scripts must be recovered to make a faithful benchmark claim.

## Security boundaries

This is a trusted-network research prototype, not a hardened multi-tenant service:

- All non-health routes require a shared Bearer secret; there is no per-user role system or distinct read/admin privilege.
- Peer destinations must match a static environment allowlist; metadata alone cannot authorize arbitrary destinations. Redirects and environment HTTP proxies are disabled.
- The static allowlist is not full DNS-rebinding protection. Configure trusted DNS, network egress rules, and no untrusted peer-controlled DNS. Do not accept arbitrary internet node registrations.
- Shared-secret peers can impersonate one another; per-node mutual TLS, signed events, tenant isolation, replay policies, and token rotation are not implemented.
- HTTP bodies, query length/tokens, peer count, decoded peer response size, and collection size have explicit caps. There is no rate limiter, deadline across the entire fan-out, pagination, or production backpressure system.
- Compose MongoDB has authentication disabled on its private Docker network. Do not expose it; other containers/users on that network are trusted. Real deployment needs MongoDB auth/TLS, least-privilege users, isolated networks, and managed secrets.
- Local Compose API ports bind to loopback only. Configure TLS, ingress filtering, reverse-proxy limits, monitoring, backups, and access audit before any non-local deployment.

## Paper mapping

| Paper element | This starter |
|---|---|
| Syncmesh function + local database + separate listener | FastAPI handler, MongoDB, standalone change-stream process |
| REST envelope containing GraphQL | Actual GraphQL parser/validator/executor and fixed weather schema |
| Collect/aggregate across saved and explicit nodes | One-hop, sequential, local-first queries with explicit failures |
| Radius-based nearest-node filtering | Haversine distances computed per request; not cached |
| Metadata CRUD and subscriptions | Authenticated manual `/meta/nodes` management |
| Origin + database ID replica identity | Stable origin URL + local UUID; origin-qualified replica ID |
| Event create/update/delete forwarding | Upsert snapshots/delete tombstones in separate replica collection |
| Stateless FaaS | Durable state externalized; optional watchdog recipe, not a tested OpenFaaS deployment |
| MongoDB 5.0.2/faasd/GCP benchmark | New MongoDB 7.0 local Compose configuration; old benchmark not reproduced |
| Terraform + centralized/sharded comparisons | Not reconstructed; no original scripts supplied |

## Repository files

```text
syncmesh/
  app.py          # HTTP API and authentication
  config.py       # Explicit limits, static peers, environment
  messages.py     # Validated request, measurement, peer, event models
  graphql_api.py  # Small real GraphQL schema and execution
  store.py        # Mongo persistence, sums/counts, conditional replica updates
  mesh.py         # One-hop federation, geographic selection, response merge
  listener.py     # Separate best-effort Mongo change-stream listener
scripts/
  ingest_csv.py   # Genuine data ingestion
  register_mesh.py
  benchmark.py    # Real client measurements only
deploy/           # Replica init + optional watchdog recipe
examples/         # Query JSON + empty CSV template
tests/            # Isolated software checks, not benchmark observations
```

See `TESTING.md` for what was actually executed. Package ranges are not a frozen environment; pin reviewed dependency versions and image digests before reproducible experiments. Choose a code license after confirming institutional/employer rights; no license is presumed for you. `CITATION.cff` identifies the associated manuscript without inventing a DOI, venue, or publication date.
