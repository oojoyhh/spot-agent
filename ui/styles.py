"""StudySpot Streamlit visual theme."""

from __future__ import annotations

import streamlit as st


def apply_theme() -> None:
    """Apply the shared visual language used by the demo screen."""
    st.markdown(
        """
        <style>
        :root {
            --studyspot-blue: #3349c8;
            --studyspot-blue-dark: #25389f;
            --studyspot-ink: #182230;
            --studyspot-muted: #667085;
            --studyspot-border: #d9dee8;
            --studyspot-surface: #f5f7fb;
        }
        .stApp { background: var(--studyspot-surface); }
        [data-testid="stAppViewContainer"] > .main .block-container {
            max-width: 1240px;
            padding-top: 2.1rem;
            padding-bottom: 5rem;
        }
        [data-testid="stSidebar"] {
            background: #eef1f7;
            border-right: 1px solid var(--studyspot-border);
        }
        [data-testid="stSidebar"] [data-testid="stForm"] {
            border: 0;
            padding: 0;
        }
        [data-testid="stSidebar"] .stButton > button,
        [data-testid="stSidebar"] [data-testid="stFormSubmitButton"] > button {
            min-height: 2.8rem;
        }
        [data-testid="stVerticalBlockBorderWrapper"] {
            background: #ffffff;
            border-color: var(--studyspot-border);
            border-radius: 14px;
            box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
        }
        div[data-testid="stMetric"] {
            background: #f8f9fc;
            border: 1px solid #e4e7ec;
            border-radius: 10px;
            padding: 0.65rem 0.8rem;
        }
        div[data-testid="stMetricValue"] {
            color: var(--studyspot-blue);
            font-weight: 750;
        }
        div[data-testid="stProgress"] > div > div > div > div {
            background-color: var(--studyspot-blue);
        }
        .stButton > button[kind="primary"],
        [data-testid="stFormSubmitButton"] button {
            background: var(--studyspot-blue) !important;
            border-color: var(--studyspot-blue) !important;
            color: #ffffff !important;
            font-weight: 700;
        }
        .stButton > button[kind="primary"]:hover,
        [data-testid="stFormSubmitButton"] button:hover {
            background: var(--studyspot-blue-dark) !important;
            border-color: var(--studyspot-blue-dark) !important;
        }
        [data-testid="stTabs"] [data-baseweb="tab-list"] {
            gap: 0.5rem;
        }
        [data-testid="stTabs"] button[role="tab"] {
            border-radius: 8px 8px 0 0;
            padding-inline: 1rem;
        }
        .studyspot-eyebrow {
            color: var(--studyspot-blue);
            font-size: .78rem;
            font-weight: 800;
            letter-spacing: .08em;
            margin-bottom: .2rem;
            text-transform: uppercase;
        }
        .studyspot-subtitle {
            color: var(--studyspot-muted);
            font-size: 1rem;
            margin: -.35rem 0 1.3rem;
        }
        .studyspot-card-title {
            color: var(--studyspot-ink);
            font-size: 1.28rem;
            font-weight: 800;
            line-height: 1.3;
            margin-top: .15rem;
        }
        .studyspot-rank {
            color: var(--studyspot-muted);
            font-size: .82rem;
            font-weight: 700;
        }
        .studyspot-score {
            color: var(--studyspot-blue);
            font-size: 1.95rem;
            font-weight: 800;
            line-height: 1;
            text-align: right;
        }
        .studyspot-score small {
            color: var(--studyspot-muted);
            font-size: .78rem;
            font-weight: 600;
        }
        .studyspot-section-label {
            color: #344054;
            font-size: .86rem;
            font-weight: 800;
            margin-bottom: .1rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
