"""Supabase Auth + RLS-protected project libraries. No privileged keys or global sessions."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


class CloudError(OSError):
    """Safe, user-facing error; never include raw auth responses or credentials."""


class ConflictError(CloudError):
    pass


@dataclass(frozen=True)
class CloudConfig:
    url: str
    publishable_key: str
    app_url: str = ""


def load_config():
    if os.environ.get("JUMBO_CLOUD_DISABLED") == "1":
        return None
    path = Path(__file__).with_name("cloud_config.json")
    data = json.loads(path.read_text()) if path.exists() else {}
    url = os.environ.get("SUPABASE_URL", data.get("url", "")).rstrip("/")
    key = os.environ.get("SUPABASE_PUBLISHABLE_KEY", data.get("publishable_key", ""))
    if not url and not key:
        return None
    if urlparse(url).scheme != "https" or not key.startswith("sb_publishable_"):
        raise CloudError("Configure an HTTPS Supabase URL and a publishable API key.")
    return CloudConfig(url, key, os.environ.get("JUMBO_APP_URL", data.get("app_url", "")))


class CloudClient:
    def __init__(self, config, session=None):
        self.config = config
        # Owned by one Streamlit session only; refresh updates this same dictionary.
        self.session = session if session is not None else {}

    def _request(self, path, method="GET", data=None, authenticated=False):
        headers = {"apikey": self.config.publishable_key, "Content-Type": "application/json"}
        if authenticated:
            self._ensure_session()
            headers["Authorization"] = "Bearer " + self.session["access_token"]
        if path.startswith("/rest/"):
            headers["Prefer"] = "return=representation"
        payload = json.dumps(data, allow_nan=False).encode() if data is not None else None
        request = Request(self.config.url + path, data=payload, headers=headers, method=method)
        try:
            with urlopen(request, timeout=15) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except HTTPError as exc:
            # Do not display the response body: it can contain account details.
            if exc.code == 409:
                raise ConflictError("The cloud library changed in another session. Export your draft, then reload the cloud library before merging changes.") from None
            if exc.code in (400, 401, 403, 422) and path.startswith("/auth/"):
                raise CloudError("Authentication failed. Check your email and password, confirm your email, or sign in again.") from None
            if exc.code in (401, 403):
                raise CloudError("Your cloud session is unavailable. Export your draft and sign in again.") from None
            if exc.code == 429:
                raise CloudError("Too many requests. Please wait before trying again.") from None
            raise CloudError("Cloud storage is unavailable. Your changes remain in this session; export a backup and retry later.") from None
        except (URLError, TimeoutError, OSError, json.JSONDecodeError):
            raise CloudError("Could not reach cloud storage. Your changes remain in this session; export a backup and retry later.") from None

    def _set_session(self, payload):
        if not isinstance(payload, dict) or not payload.get("access_token") or not payload.get("user", {}).get("id"):
            raise CloudError("Sign-in did not return a valid session. Confirm your email and try again.")
        self.session.clear()
        self.session.update({
            "access_token": payload["access_token"],
            "refresh_token": payload["refresh_token"],
            "expires_at": time.time() + payload.get("expires_in", 3600),
            "user_id": payload["user"]["id"],
            "email": payload["user"].get("email", ""),
        })

    def sign_in(self, email, password):
        self._set_session(self._request("/auth/v1/token?grant_type=password", "POST", {"email": email.strip(), "password": password}))
        return self.session

    def sign_up(self, email, password):
        query = "?" + urlencode({"redirect_to": self.config.app_url}) if self.config.app_url else ""
        self._request("/auth/v1/signup" + query, "POST", {"email": email.strip(), "password": password})

    def _ensure_session(self):
        if not self.session.get("access_token"):
            raise CloudError("Sign in to save projects to your account.")
        if self.session.get("expires_at", 0) <= time.time() + 60:
            payload = self._request("/auth/v1/token?grant_type=refresh_token", "POST", {"refresh_token": self.session["refresh_token"]})
            self._set_session(payload)

    def sign_out(self):
        try:
            self._request("/auth/v1/logout?scope=local", "POST", authenticated=True)
        finally:
            self.session.clear()

    def load_library(self):
        self._ensure_session()
        query = urlencode({"user_id": "eq." + self.session["user_id"], "select": "projects,revision"})
        rows = self._request("/rest/v1/project_libraries?" + query, authenticated=True)
        if not rows:
            return {}, 0
        row = rows[0]
        if not isinstance(row.get("projects"), dict) or not isinstance(row.get("revision"), int):
            raise CloudError("The cloud library has an unsupported format. Contact the app administrator.")
        return row["projects"], row["revision"]

    def save_library(self, projects, revision):
        self._ensure_session()
        if not isinstance(projects, dict):
            raise ValueError("A project library must be an object.")
        if len(json.dumps(projects, allow_nan=False).encode()) > 8_000_000:
            raise CloudError("This library is too large for cloud storage. Export a backup and reduce the library size.")
        if revision == 0:
            rows = self._request("/rest/v1/project_libraries", "POST", {
                "user_id": self.session["user_id"], "projects": projects,
            }, authenticated=True)
        else:
            query = urlencode({"user_id": "eq." + self.session["user_id"], "revision": "eq." + str(revision)})
            rows = self._request("/rest/v1/project_libraries?" + query, "PATCH", {"projects": projects}, authenticated=True)
        if not rows:
            raise ConflictError("The cloud library changed in another session. Export your draft, then reload the cloud library before merging changes.")
        return rows[0]["revision"]
