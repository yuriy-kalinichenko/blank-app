"""Presentation only: shared visual language for the Streamlit workspace."""

from html import escape
from pathlib import Path

import streamlit as st


def apply_theme():
    # Resolve from this module, including when AppTest runs from a temporary cwd.
    st.html(Path(__file__).with_name("workspace.css"))


def render_sidebar(build_version):
    st.html('''<div class="jumbo-brand"><span class="jumbo-monogram">J</span>
        <div><strong>JUMBO</strong><span>LOCATION INTELLIGENCE</span></div></div>
        <div class="sidebar-label">YOUR WORKSPACE</div>
        <nav class="jumbo-nav" aria-label="Workspace sections">
        <a href="#project-workspace" target="_self">01 <span>Projects &amp; decisions</span></a>
        <a href="#site-analysis" target="_self">02 <span>Location analysis</span></a>
        <a href="#portfolio" target="_self">03 <span>Portfolio comparison</span></a>
        <a href="#discover" target="_self">04 <span>Discover locations</span></a>
        </nav>''')
    st.divider()
    st.caption("ACCOUNT & STORAGE")
    # Render the account panel below this function, in the same sidebar context.


def render_header():
    with st.container(key="workspace_hero"):
        st.html('<div class="workspace-eyebrow">RETAIL EXPANSION / DECISION WORKSPACE</div>')
        st.title("Jumbo Location Analyzer")
        st.caption("Find the right location. Understand the opportunity. Build your investment case.")


def render_context(library, active_name, stage, cloud_enabled):
    signed_in = bool(st.session_state.get("_cloud_session"))
    storage = "Private cloud account" if signed_in else "Guest session" if cloud_enabled else "Local workspace"
    project = active_name or "New unsaved project"
    st.html(f'''<div class="workspace-context">
        <span><span class="context-dot"></span>{escape(storage)}</span>
        <span><strong>{len(library)}</strong> projects in library</span>
        <span class="context-project">{escape(project)}</span>
        <span class="stage-tag">{escape(stage)}</span></div>''')


def section_anchor(name):
    # Callers provide fixed internal names, never provider/user content.
    st.html(f'<div id="{escape(name, quote=True)}" class="workspace-anchor"></div>')


def render_analysis_intro():
    st.html('''<div class="analysis-intro"><span class="section-number">02</span>
        <div><h2>Location analysis</h2><p>Explore the catchment, competition and investment potential of a site.</p></div></div>''')


def render_empty_analysis():
    st.html('''<div class="analysis-empty">
        <div class="empty-symbol" aria-hidden="true">◎</div>
        <div><h3>Your next location starts here</h3>
        <p>Enter a site above and select <strong>Analyze location</strong> to open its map and evidence.</p>
        <div class="analysis-steps"><span>01 &nbsp; Locate the site</span><span>02 &nbsp; Review the market</span><span>03 &nbsp; Test the economics</span></div>
        </div></div>''')
