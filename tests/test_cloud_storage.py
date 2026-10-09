import io
import json
import time
from urllib.error import HTTPError, URLError

import pytest

import cloud_storage
from cloud_storage import CloudClient, CloudConfig, CloudError, ConflictError


CONFIG = CloudConfig("https://test.supabase.co", "sb_publishable_test")


def session():
    return {"user_id": "owner-a", "email": "a@example.test", "access_token": "user-token", "refresh_token": "refresh", "expires_at": time.time() + 3600}


def response(value):
    return io.BytesIO(json.dumps(value).encode())


def test_expired_session_refreshes_before_loading_and_keeps_new_tokens(monkeypatch):
    state = session()
    state["expires_at"] = 0
    requests = []
    def request(req, timeout):
        requests.append(req)
        if "grant_type=refresh_token" in req.full_url:
            assert json.loads(req.data) == {"refresh_token": "refresh"}
            return response({"access_token": "new-token", "refresh_token": "new-refresh", "expires_in": 3600, "user": {"id": "owner-a"}})
        assert req.get_header("Authorization") == "Bearer new-token"
        return response([{"projects": {"Kyiv": {"area": 4500}}, "revision": 7}])
    monkeypatch.setattr(cloud_storage, "urlopen", request)
    library, revision = CloudClient(CONFIG, state).load_library()
    assert library["Kyiv"]["area"] == 4500 and revision == 7
    assert state["refresh_token"] == "new-refresh"
    assert len(requests) == 2


def test_concurrent_write_is_rejected_without_an_upsert(monkeypatch):
    requests = []
    def request(req, timeout):
        requests.append(req)
        assert req.method == "PATCH"
        assert "revision=eq.3" in req.full_url
        return response([])
    monkeypatch.setattr(cloud_storage, "urlopen", request)
    with pytest.raises(ConflictError, match="another session"):
        CloudClient(CONFIG, session()).save_library({"Draft": {}}, 3)
    assert len(requests) == 1


def test_racing_first_save_conflicts_and_never_overwrites(monkeypatch):
    def request(req, timeout):
        assert req.method == "POST"
        raise HTTPError(req.full_url, 409, "conflict", {}, io.BytesIO(b"private details"))
    monkeypatch.setattr(cloud_storage, "urlopen", request)
    with pytest.raises(ConflictError):
        CloudClient(CONFIG, session()).save_library({}, 0)


def test_auth_failure_does_not_expose_server_response(monkeypatch):
    def request(req, timeout):
        raise HTTPError(req.full_url, 400, "account-specific secret", {}, io.BytesIO(b"private details"))
    monkeypatch.setattr(cloud_storage, "urlopen", request)
    with pytest.raises(CloudError) as error:
        CloudClient(CONFIG).sign_in("a@example.test", "private-password")
    assert "private" not in str(error.value)
    assert "Authentication failed" in str(error.value)


def test_guest_cannot_write_and_logout_clears_tokens_even_during_outage(monkeypatch):
    def request(req, timeout):
        raise URLError("offline")
    monkeypatch.setattr(cloud_storage, "urlopen", request)
    with pytest.raises(CloudError, match="Sign in"):
        CloudClient(CONFIG).save_library({}, 0)
    state = session()
    with pytest.raises(CloudError):
        CloudClient(CONFIG, state).sign_out()
    assert state == {}
