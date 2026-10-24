"""Small software fixtures only; no real sensor/benchmark data is simulated."""
import hashlib
import json

from bson.timestamp import Timestamp
from fastapi.testclient import TestClient
import httpx
import mongomock
import pytest

from syncmesh.app import create_app
from syncmesh.config import Settings
from syncmesh.listener import make_event, dispatch
from syncmesh.mesh import distance_km
from syncmesh.messages import ChangeEvent, MeshRequest
from syncmesh.store import MongoStore

TOKEN = "software-test-token-not-for-use-1234567890"
URL1, URL2 = "http://node1:8080", "http://node2:8080"
QUERY = "query { measurements { id replica_id origin sensor_id timestamp temperature humidity pressure } }"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def settings(url=URL1, peers=(URL2,), **kwargs):
    return Settings(node_url=url, token=TOKEN, allowed_peers=peers, **kwargs)


def record(temperature=0., humidity=None):
    return dict(sensor_id="SOFTWARE_FIXTURE", timestamp="2020-01-01T00:00:00Z",
                temperature=temperature, humidity=humidity, pressure=None)


@pytest.fixture
def mesh():
    s1, s2 = settings(), settings(URL2, (URL1,))
    st1, st2 = MongoStore(URL1, mongomock.MongoClient()), MongoStore(URL2, mongomock.MongoClient())
    with TestClient(create_app(s2, st2)) as remote:
        def route(request):
            assert str(request.url) == URL2 + "/request" or str(request.url) == URL2 + "/events"
            assert request.headers["authorization"] == AUTH["Authorization"]
            response = remote.post(request.url.path, content=request.content, headers={**AUTH, "Content-Type": "application/json"})
            return httpx.Response(response.status_code, json=response.json())
        transport = httpx.MockTransport(route)
        with TestClient(create_app(s1, st1, transport)) as local:
            yield local, remote, st1, st2


def test_auth_and_empty_query(mesh):
    local, _, _, _ = mesh
    assert local.post("/request", json={"query": QUERY}).status_code == 401
    response = local.post("/request", headers=AUTH, json={"query": QUERY}).json()
    assert response["count"] == 0 and not response["partial"]


def test_local_crud_and_no_mutation_forward(mesh):
    local, _, _, remote_store = mesh
    query = "mutation($x: MeasurementInput!) { createMeasurement(input: $x) { id temperature } }"
    reply = local.post("/request", headers=AUTH, json={"query": query, "variables": {"x": record(2)}})
    assert reply.status_code == 200
    identifier = reply.json()["data"]["createMeasurement"]["id"]
    assert remote_store.records.count_documents({}) == 0
    query = 'mutation($x: MeasurementInput!, $id: ID!) { updateMeasurement(id: $id, input: $x) { temperature } }'
    response = local.post("/request", headers=AUTH, json={"query": query, "variables": {"x": record(3), "id": identifier}})
    assert response.json()["data"]["updateMeasurement"]["temperature"] == 3
    response = local.post("/request", headers=AUTH, json={"query": f'mutation {{ deleteMeasurement(id: "{identifier}") }}'})
    assert response.json()["data"]["deleteMeasurement"]
    assert local.post("/request", headers=AUTH, json={"query": QUERY}).json()["count"] == 0


def test_two_node_collection_alias_and_no_recursive_fanout(mesh):
    local, _, st1, st2 = mesh
    st1.create(record(0))
    st2.create(record(10))
    # Reciprocal metadata would recurse without the local_only one-hop guard.
    st1.put_peer(dict(url=URL2, latitude=42., longitude=23., subscribed=False))
    st2.put_peer(dict(url=URL1, latitude=42., longitude=23., subscribed=False))
    response = local.post("/request", headers=AUTH, json={"query": "query { readings: measurements { t: temperature } }"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 2 and body["queried_nodes"] == [URL1, URL2]
    assert body["data"]["readings"] == [{"t": 0.}, {"t": 10.}]


def test_weighted_aggregation_missing_fields(mesh):
    local, _, st1, st2 = mesh
    st1.create(record(0, None))
    for _ in range(3):
        st2.create(record(10, 20))
    response = local.post("/request", headers=AUTH, json={"query": QUERY, "request_type": "aggregate", "external_nodes": [URL2]})
    assert response.status_code == 200, response.text
    stats = response.json()["statistics"]
    assert stats["count"] == 4 and stats["means"]["temperature"] == 7.5
    assert stats["counts"]["humidity"] == 3 and stats["means"]["humidity"] == 20
    assert stats["means"]["pressure"] is None


def test_radius_and_missing_peer_coordinates(mesh):
    local, _, _, st2 = mesh
    st2.create(record())
    assert distance_km(42, 23, 42, 23) == 0
    body = {"query": QUERY, "external_nodes": [URL2], "radius": 1}
    assert local.post("/request", headers=AUTH, json=body).status_code == 400
    assert local.put("/meta/nodes", headers=AUTH, json=dict(url=URL2, latitude=50, longitude=23)).status_code == 200
    assert local.post("/request", headers=AUTH, json=body).json()["count"] == 0
    assert local.get("/meta/nodes", headers=AUTH).json()[0]["url"] == URL2
    assert local.delete("/meta/nodes", headers=AUTH, params={"url": URL2}).json()["deleted"]


def test_filter_applies_on_both_nodes(mesh):
    local, _, st1, st2 = mesh
    st1.create(record(0))
    st2.create(record(10))
    query = 'query($filter: MeasurementFilter) { measurements(filter: $filter) { temperature } }'
    body = dict(query=query, variables={"filter": {"start": "2021-01-01T00:00:00Z"}}, external_nodes=[URL2])
    response = local.post("/request", headers=AUTH, json=body)
    assert response.status_code == 200 and response.json()["count"] == 0


def test_allowlist_and_schema_validation(mesh):
    local, _, _, _ = mesh
    assert local.post("/request", headers=AUTH, json={"query": QUERY, "external_nodes": ["http://untrusted:8080"]}).status_code == 400
    assert local.post("/request", headers=AUTH, json={"query": QUERY, "database": "admin"}).status_code == 422
    assert local.post("/request", headers=AUTH, json={"query": "query { __schema { queryType { name } } }"}).status_code == 400
    assert local.post("/request", headers=AUTH, json={"query": "query { measurements { id } } query X { measurements { id } }"}).status_code == 400
    assert local.post("/request", headers=AUTH, json={"query": "not graphql"}).status_code == 400
    assert local.post("/request", headers=AUTH, json={"query": "query { measurements @skip(if: true) { id } }"}).status_code == 400


def event(version="00000000000000000001:0000000001", operation="upsert"):
    return ChangeEvent(event_id=hashlib.sha256(version.encode()).hexdigest(), origin=URL2, document_id="fixture-id",
        version=version, operation=operation, measurement=record(10) if operation == "upsert" else None)


def test_replication_idempotency_stale_events_tombstones_and_no_double_count(mesh):
    local, _, st1, st2 = mesh
    item = event()
    first = local.post("/events", headers=AUTH, json=item.model_dump())
    assert first.status_code == 200 and first.json()["applied"]
    assert not local.post("/events", headers=AUTH, json=item.model_dump()).json()["applied"]
    assert local.post("/request", headers=AUTH, json={"query": QUERY}).json()["count"] == 0
    body = {"query": QUERY, "local_only": True, "include_replicas": True}
    assert local.post("/request", headers=AUTH, json=body).json()["count"] == 1
    deletion = event("00000000000000000002:0000000001", "delete")
    assert local.post("/events", headers=AUTH, json=deletion.model_dump()).json()["applied"]
    assert not local.post("/events", headers=AUTH, json=item.model_dump()).json()["applied"]
    assert local.post("/request", headers=AUTH, json=body).json()["count"] == 0


def test_listener_event_conversion():
    change = dict(operationType="insert", documentKey={"_id": "fixture-id"}, _id={"token": "fixture-token"},
                  clusterTime=Timestamp(12, 3), fullDocument=record(5))
    result = make_event(change, URL1)
    assert result.version == "00000000000000000012:0000000003"
    assert len(result.event_id) == 64 and result.measurement.temperature == 5
    change["operationType"] = "delete"
    assert make_event(change, URL1).operation == "delete"
    change["operationType"], change["fullDocument"] = "update", None
    assert make_event(change, URL1) is None


def test_listener_forwards_subscribed_peers_only():
    st = MongoStore(URL1, mongomock.MongoClient())
    st.put_peer(dict(url=URL2, latitude=42, longitude=23, subscribed=True))
    calls = []
    def route(req):
        calls.append(str(req.url))
        return httpx.Response(200, json={"applied": True})
    with httpx.Client(transport=httpx.MockTransport(route)) as client:
        assert dispatch(st, settings(), client, event()) == []
    assert calls == [URL2 + "/events"]


def test_failed_peer_exposes_partial_response():
    st = MongoStore(URL1, mongomock.MongoClient())
    st.create(record(2))
    def broken(req):
        raise httpx.ConnectError("SOFTWARE TEST FAILURE")
    with TestClient(create_app(settings(), st, httpx.MockTransport(broken))) as client:
        response = client.post("/request", headers=AUTH, json={"query": QUERY, "external_nodes": [URL2]})
        body = response.json()
        assert body["partial"] and body["count"] == 1
        assert body["failed_nodes"][0]["node"] == URL2


def test_timezones_record_caps_and_body_limit():
    st = MongoStore(URL1, mongomock.MongoClient())
    with pytest.raises(ValueError):
        st.create({**record(), "timestamp": "2020-01-01T00:00:00"})
    st.create(record())
    st.create(record())
    with TestClient(create_app(settings(max_records=1), st)) as client:
        assert client.post("/request", headers=AUTH, json={"query": QUERY}).status_code == 400
        assert client.post("/request", headers=AUTH, content=b" "*65537).status_code == 413
    with pytest.raises(ValueError):
        Settings(node_url=URL1, token="short")


def test_replica_and_mutation_federation_guards(mesh):
    local, _, _, _ = mesh
    assert local.post("/request", headers=AUTH, json=dict(query=QUERY, include_replicas=True)).status_code == 400
    assert local.post("/request", headers=AUTH, json=dict(query=QUERY, local_only=True,
        include_replicas=True, request_type="aggregate")).status_code == 400
    mutation = "mutation($x: MeasurementInput!) { createMeasurement(input: $x) { id } }"
    assert local.post("/request", headers=AUTH, json=dict(query=mutation, variables={"x": record()}, external_nodes=[URL2])).status_code == 400


def test_peer_byte_limit_returns_explicit_partial():
    st = MongoStore(URL1, mongomock.MongoClient())
    def oversized(req):
        return httpx.Response(200, content=b" " * 65)
    with TestClient(create_app(settings(max_response_bytes=64), st, httpx.MockTransport(oversized))) as client:
        response = client.post("/request", headers=AUTH, json=dict(query=QUERY, external_nodes=[URL2]))
        assert response.json()["partial"]
        assert response.json()["failed_nodes"][0]["error"] == "ValueError"


def test_redirect_never_followed():
    st = MongoStore(URL1, mongomock.MongoClient())
    calls = []
    def redirect(req):
        calls.append(str(req.url))
        return httpx.Response(302, headers={"Location": "http://untrusted:8080/request"})
    with TestClient(create_app(settings(), st, httpx.MockTransport(redirect))) as client:
        response = client.post("/request", headers=AUTH, json=dict(query=QUERY, external_nodes=[URL2]))
        assert response.json()["partial"]
    assert calls == [URL2 + "/request"]


def test_newer_replica_update_allowed_but_foreign_origin_denied(mesh):
    local, _, _, _ = mesh
    first, newer = event(), event("00000000000000000003:0000000001")
    newer.measurement.temperature = 22
    assert local.post("/events", headers=AUTH, json=first.model_dump()).json()["applied"]
    assert local.post("/events", headers=AUTH, json=newer.model_dump()).json()["applied"]
    response = local.post("/request", headers=AUTH, json=dict(query=QUERY, local_only=True, include_replicas=True))
    assert response.json()["data"]["measurements"][0]["temperature"] == 22
    bad = {**newer.model_dump(), "origin": "http://unknown:8080"}
    assert local.post("/events", headers=AUTH, json=bad).status_code == 400
