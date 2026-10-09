"""Optional cloud account UI; all account data is scoped to one browser session."""

from copy import deepcopy
import streamlit as st

from cloud_storage import CloudClient, CloudError
from project_library import export_project_library, validate_project_library


def save_cloud_library(config, projects):
    try:
        session = st.session_state.get("_cloud_session")
        if not session:
            raise CloudError("Guest changes are only in this browser session. Sign in to save to the cloud, or export a backup.")
        revision = CloudClient(config, session).save_library(projects, st.session_state["_cloud_revision"])
        st.session_state["_cloud_revision"] = revision
        st.session_state.pop("_storage_error", None)
    except (CloudError, ValueError) as exc:
        message = str(exc) if isinstance(exc, CloudError) else "The library contains unsupported values. Export a backup before correcting them."
        st.session_state["_storage_error"] = message
        raise CloudError(message) from None


def _read_library(client):
    projects, revision = client.load_library()
    try:
        return (validate_project_library({"projects": projects}) if projects else {}), revision
    except (ValueError, TypeError):
        raise CloudError("The cloud library could not be read. No local projects were replaced.") from None


def render_cloud_workspace(config, build_version):
    if config is None:
        return
    session = st.session_state.get("_cloud_session")
    with st.expander("Cloud projects", expanded=not bool(session) or bool(st.session_state.get("_storage_error"))):
        if not session:
            st.caption("Guest mode · export a backup before closing. Sign in to save projects across devices.")
            st.caption("Use your Jumbo app account. New here? Create an account and confirm your email, then sign in.")
            with st.form("cloud_sign_in", clear_on_submit=True):
                email = st.text_input("Account email", key="cloud_email", autocomplete="email")
                password = st.text_input("Account password", type="password", key="cloud_password", autocomplete="current-password")
                sign_in = st.form_submit_button("Sign in", type="primary", use_container_width=True)
                sign_up = st.form_submit_button("Create account", use_container_width=True)
            if sign_in or sign_up:
                if not email.strip() or not password:
                    st.warning("Enter your email and password.")
                elif sign_up and len(password) < 12:
                    st.warning("Choose a password with at least 12 characters.")
                else:
                    client = CloudClient(config)
                    try:
                        if sign_up:
                            client.sign_up(email, password)
                            st.success("Check your email for a confirmation link, then return here and sign in. If you already have an account, use Sign in.")
                        else:
                            client.sign_in(email, password)
                            projects, revision = _read_library(client)
                            guest_projects = deepcopy(st.session_state.get("project_library", {}))
                            # Clear every project/widget/cache entry before changing identity.
                            st.session_state.clear()
                            st.session_state.update({"_cloud_session": client.session, "_cloud_revision": revision, "project_library": projects})
                            if guest_projects:
                                st.session_state["_cloud_import_candidate"] = guest_projects
                            st.rerun()
                    except CloudError as exc:
                        st.error(str(exc))
            return

        st.caption(f"Signed in: {session.get('email', '')} · projects are private to this account.")
        problem = st.session_state.get("_storage_error")
        if problem:
            st.warning("Cloud save incomplete. " + problem)
        else:
            st.caption("Saved changes sync to Supabase. Sign in again after opening a new browser session.")

        library = st.session_state.get("project_library", {})
        st.download_button("Export current library", export_project_library(library, build_version),
                           file_name="jumbo_location_projects.json", mime="application/json", key="cloud_backup")
        candidate = st.session_state.get("_cloud_import_candidate")
        if candidate:
            st.info(f"{len(candidate)} project(s) from your previous guest session are available to copy into this account.")
            st.download_button("Export guest projects", export_project_library(candidate, build_version),
                               file_name="jumbo_guest_projects.json", mime="application/json", key="cloud_guest_backup")
            if st.button("Copy guest projects to my account", key="cloud_copy_guest"):
                merged = deepcopy(library)
                # Preserve BOTH records if names collide; never overwrite cloud records implicitly.
                for name, project in candidate.items():
                    if merged.get(name) == project:
                        continue
                    target, suffix = name, 1
                    while target in merged:
                        target = f"{name} (import {suffix})"
                        suffix += 1
                    merged[target] = project
                try:
                    save_cloud_library(config, merged)
                    st.session_state["project_library"] = merged
                    st.session_state.pop("_cloud_import_candidate", None)
                    st.session_state["_project_flash"] = "Guest projects saved to your account."
                    st.rerun()
                except CloudError as exc:
                    st.error(str(exc))

        discard = False
        if problem or candidate:
            discard = st.checkbox("I have exported any unsaved projects and can discard local copies.", key="cloud_discard")
        if st.button("Retry cloud save", disabled=not bool(problem), key="cloud_retry"):
            try:
                save_cloud_library(config, library)
                st.rerun()
            except CloudError as exc:
                st.error(str(exc))
        if st.button("Reload cloud library", disabled=bool(problem) and not discard, key="cloud_reload"):
            try:
                projects, revision = _read_library(CloudClient(config, session))
                st.session_state.clear()
                st.session_state.update({"_cloud_session": session, "_cloud_revision": revision, "project_library": projects})
                if candidate:
                    st.session_state["_cloud_import_candidate"] = candidate
                st.rerun()
            except CloudError as exc:
                st.error(str(exc))
        if st.button("Sign out", disabled=bool(problem or candidate) and not discard, key="cloud_logout"):
            try:
                CloudClient(config, session).sign_out()
            except CloudError:
                # Even during an outage, remove all local account data and tokens.
                pass
            st.session_state.clear()
            st.rerun()
