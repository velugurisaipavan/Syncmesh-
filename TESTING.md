# Validation status

## Executed in the generation environment

- 16 software tests passed.
- Python source and test modules compiled successfully.
- Editable installation using the dev extra succeeded.
- CSV-ingest and benchmark command-line help completed successfully.
- Compose and citation YAML parsed, and the 3-node / 3-volume / independent replica-set configuration was structurally checked.

The software tests cover authenticated local GraphQL CRUD, GraphQL variable/alias handling, a two-node in-process HTTP federation path, one-hop loop prevention, unequal-count weighted aggregation and null-field counts, filtering, geographic selection, metadata CRUD, peer allowlists, invalid query/schema rejection, payload/peer-byte limits, redirect refusal, explicit partial failures, event conversion, subscription dispatch, replica updates, duplicate/stale suppression, tombstones, and replica exclusion from aggregate queries.

Tests use small deterministic software fixtures, mongomock, FastAPI TestClient, and httpx MockTransport. They do not represent actual weather observations, live distributed deployment measurements, or paper benchmark results. Both HTTP applications execute in process; the peer transport is mocked. MongoDB driver operations execute against mongomock, not a running MongoDB replica set.

## Not executed or established

Docker is unavailable in this environment. No container build/start, real MongoDB change stream, real resume-token recovery, live concurrent conditional-update stress test, GCP/Terraform deployment, OpenFaaS/faasd deployment, multi-machine networking, real sensor CSV import, benchmark measurement, total packet traffic, or performance comparison was run. The optional watchdog Dockerfile was not built. Security controls are prototype safeguards, not a penetration-test certification or production approval.

The installed Starlette TestClient emitted an httpx deprecation warning; tests passed. Dependency ranges are not a frozen lockfile. Validate exact reviewed versions and image digests in your own environment.

## Generation environment

- Python: 3.12.8
- fastapi: 0.162.0
- starlette: 1.9.0
- httpx: 0.28.1
- pymongo: 4.19.0
- graphql-core: 3.2.13
- mongomock: 4.3.0
- pytest: 8.3.5
- uvicorn: 0.54.0
