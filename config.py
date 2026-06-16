"""
config.py — Loads all settings from the .env file.
Do not put actual values here. Edit the .env file instead.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the project root (same folder as this file)
load_dotenv(Path(__file__).parent / ".env")

def _require(key: str) -> str:
    """Get an env variable, raise a clear error if it's missing or empty."""
    val = os.getenv(key, "").strip()
    if not val:
        raise EnvironmentError(
            f"\n\n  Missing required config: '{key}' is not set in your .env file.\n"
            f"  Open .env and fill in the value for {key}.\n"
        )
    return val

def _optional(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()

# --- GitLab ---
GITLAB_URL          = _require("GITLAB_URL").rstrip("/")
GITLAB_PAT          = _require("GITLAB_PAT")

# --- GitHub ---
GITHUB_PAT          = _require("GITHUB_PAT")

# --- Git identity ---
GIT_SYNC_USER       = _require("GIT_SYNC_USER")
GIT_SYNC_EMAIL      = _require("GIT_SYNC_EMAIL")

# --- Sync settings ---
SYNC_BRANCH_PREFIX  = _require("SYNC_BRANCH_PREFIX")
SYNC_SOURCE_BRANCH  = _require("SYNC_SOURCE_BRANCH")
GITLAB_RUNNER_TAG   = _require("GITLAB_RUNNER_TAG")

# --- Template project ---
TEMPLATE_PROJECT_ID  = _require("TEMPLATE_PROJECT_ID")
TEMPLATE_PROJECT_REF = _optional("TEMPLATE_PROJECT_REF", "main")

# --- Web UI ---
PROVISIONER_PORT    = int(_optional("PROVISIONER_PORT", "5001"))
PROVISIONER_HOST    = "0.0.0.0"
DEFAULT_GROUP_PATH  = _optional("DEFAULT_GROUP_PATH", "")