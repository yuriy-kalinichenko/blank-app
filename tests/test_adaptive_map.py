import io
from urllib.error import HTTPError

import pytest

from golden_context import load_adaptive_tile


def provider_error(code=400, body=b"You requested too many nodes (limit is 50000)."):
    return HTTPError("https://api.openstreetmap.org/api/0.6/map.json", code,
                     "Bad Request", {}, io.BytesIO(body))


def test_dense_tile_splits_full_area_and_deduplicates_shared_objects():
    parent = (19.8, 41.325, 19.825, 41.35)
    calls = []

    def fetch(bbox):
        calls.append(bbox)
        if bbox == parent:
            raise provider_error()
        return [{"type": "node", "id": 1}, {"type": "way", "id": len(calls)}]

    rows = load_adaptive_tile(parent, fetch)
    assert len(calls) == 5
    assert len(rows) == 5  # One common node plus one way from each quadrant.
    children = calls[1:]
    assert sum((e-w)*(n-s) for w,s,e,n in children) == pytest.approx(
        (parent[2]-parent[0])*(parent[3]-parent[1]))
    assert all(parent[0] <= w < e <= parent[2] and parent[1] <= s < n <= parent[3]
               for w,s,e,n in children)
    assert {(w,s) for w,s,e,n in children} == {
        (parent[0],parent[1]), ((parent[0]+parent[2])/2,parent[1]),
        (parent[0],(parent[1]+parent[3])/2),
        ((parent[0]+parent[2])/2,(parent[1]+parent[3])/2),
    }


@pytest.mark.parametrize("error", [
    provider_error(400, b"The parameter bbox is required"),
    provider_error(429, b"Too many requests"),
    TimeoutError("screening map budget exhausted"),
])
def test_other_failures_are_not_retried_as_smaller_requests(error):
    calls = []
    def fetch(bbox):
        calls.append(bbox)
        raise error
    with pytest.raises((RuntimeError, HTTPError, TimeoutError)):
        load_adaptive_tile((0,0,1,1), fetch)
    assert len(calls) == 1


def test_subdivision_is_bounded():
    calls = []
    def fetch(bbox):
        calls.append(bbox)
        raise provider_error()
    with pytest.raises(RuntimeError, match="too many nodes"):
        load_adaptive_tile((0,0,1,1), fetch, max_depth=2)
    assert len(calls) == 3


def test_failed_child_never_returns_successful_partial_coverage():
    calls = []
    def fetch(bbox):
        calls.append(bbox)
        if len(calls) == 1:
            raise provider_error()
        if len(calls) == 3:
            raise TimeoutError("budget exhausted")
        return [{"type":"node", "id":1}]
    with pytest.raises(TimeoutError):
        load_adaptive_tile((0,0,1,1), fetch)
    assert len(calls) == 3
