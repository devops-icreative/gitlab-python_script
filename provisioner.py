"""
provisioner.py — GitLab Project Provisioning Engine
====================================================
All GitLab API calls live here. The web UI (app.py) calls these functions.
You can also import and call these from a terminal if needed.
"""

import time
import base64
import requests
from config import (
    GITLAB_URL, GITLAB_PAT, GITHUB_PAT,
    GIT_SYNC_USER, GIT_SYNC_EMAIL,
    SYNC_BRANCH_PREFIX, SYNC_SOURCE_BRANCH, GITLAB_RUNNER_TAG,
    TEMPLATE_PROJECT_ID, TEMPLATE_PROJECT_REF,
)

# ---------------------------------------------------------------------------
# HTTP session — all requests go through this
# ---------------------------------------------------------------------------

session = requests.Session()
session.headers.update({
    "PRIVATE-TOKEN": GITLAB_PAT,
    "Content-Type": "application/json",
})

def _gl(path, **kwargs):
    """Build a full GitLab API URL."""
    return f"{GITLAB_URL.rstrip('/')}/api/v4{path}", kwargs


def _raise(resp, context=""):
    """Raise a clear error if a GitLab API call failed."""
    if not resp.ok:
        try:
            detail = resp.json().get("message") or resp.json()
        except Exception:
            detail = resp.text[:300]
        raise RuntimeError(f"GitLab API error [{context}] {resp.status_code}: {detail}")


# ---------------------------------------------------------------------------
# Step 0 — Validate inputs before doing anything
# ---------------------------------------------------------------------------

def validate_github_repo(github_url: str) -> dict:
    """
    Check that the GitHub repo exists and is accessible with the PAT.
    Returns {"owner": "...", "repo": "...", "full_name": "org/repo", "default_branch": "main"}
    """
    # Normalise: strip .git suffix and trailing slash
    url = github_url.strip().rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]

    # Accept both  https://github.com/org/repo  and  org/repo
    if "github.com/" in url:
        parts = url.split("github.com/", 1)[1].split("/")
    else:
        parts = url.strip("/").split("/")

    if len(parts) < 2:
        raise ValueError(f"Cannot parse GitHub URL: '{github_url}'. Expected format: https://github.com/org/repo")

    owner, repo = parts[0], parts[1]

    gh_resp = requests.get(
        f"https://api.github.com/repos/{owner}/{repo}",
        headers={"Authorization": f"Bearer {GITHUB_PAT}", "Accept": "application/vnd.github+json"},
        timeout=15,
    )
    if gh_resp.status_code == 404:
        raise ValueError(f"GitHub repo '{owner}/{repo}' not found or not accessible with your PAT.")
    if not gh_resp.ok:
        raise ValueError(f"GitHub API error {gh_resp.status_code}: {gh_resp.text[:200]}")

    data = gh_resp.json()
    return {
        "owner": owner,
        "repo": repo,
        "full_name": data["full_name"],
        "default_branch": data.get("default_branch", "main"),
        "description": data.get("description") or "",
    }


# ---------------------------------------------------------------------------
# Step 1 — Fetch existing GitLab groups (for the dropdown)
# ---------------------------------------------------------------------------

def get_all_groups() -> list[dict]:
    """
    Return all groups the PAT has access to, sorted alphabetically.
    Each item: {"id": 5, "full_path": "clients/clientA", "name": "clientA"}
    """
    groups = []
    page = 1
    while True:
        url, _ = _gl(f"/groups?per_page=100&page={page}&all_available=true")
        resp = session.get(url, timeout=15)
        _raise(resp, "list groups")
        batch = resp.json()
        if not batch:
            break
        groups.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    return [
        {"id": g["id"], "full_path": g["full_path"], "name": g["full_name"]}
        for g in groups
    ]


# ---------------------------------------------------------------------------
# Step 2 — Create the GitLab project (import from GitHub)
# ---------------------------------------------------------------------------

def create_project(repo_info: dict, group_id: int, project_name: str) -> dict:
    """
    Create a new GitLab project by importing from GitHub.
    Waits until the import is complete before returning.
    Returns the created project dict (includes id, path_with_namespace, web_url, default_branch).
    """
    github_clone_url = (
        f"https://oauth2:{GITHUB_PAT}@github.com/"
        f"{repo_info['full_name']}.git"
    )

    url, _ = _gl("/projects")
    payload = {
        "name": project_name,
        "import_url": github_clone_url,
        "namespace_id": group_id,
        "description": repo_info["description"],
        "visibility": "private",
        "initialize_with_readme": False,
    }

    resp = session.post(url, json=payload, timeout=30)
    _raise(resp, "create project")
    project = resp.json()
    project_id = project["id"]

    # Poll until import is finished (can take 10–60s depending on repo size)
    for attempt in range(60):
        time.sleep(5)
        status_url, _ = _gl(f"/projects/{project_id}/import")
        status_resp = session.get(status_url, timeout=15)
        _raise(status_resp, "import status")
        status = status_resp.json().get("import_status", "")
        if status == "finished":
            break
        if status == "failed":
            detail = status_resp.json().get("import_error", "unknown error")
            raise RuntimeError(f"GitLab import failed: {detail}")
        # still "started" or "scheduled" — keep waiting

    if attempt == 59:
        raise RuntimeError("Import timed out after 5 minutes. Check GitLab admin → Background jobs.")

    # Re-fetch the project to get final state (default_branch may have resolved)
    proj_url, _ = _gl(f"/projects/{project_id}")
    proj_resp = session.get(proj_url, timeout=15)
    _raise(proj_resp, "fetch project after import")
    return proj_resp.json()


# ---------------------------------------------------------------------------
# Step 3 — Enable push mirroring to GitHub
# ---------------------------------------------------------------------------

def enable_push_mirror(project_id: int, github_full_name: str) -> dict:
    """
    Configure GitLab to push-mirror this project to the GitHub repo.
    Only protected branches are mirrored — this prevents github-sync/* temp
    branches from leaking to GitHub during MR workflows.
    Returns the mirror config dict.
    """
    mirror_url = f"https://oauth2:{GITHUB_PAT}@github.com/{github_full_name}.git"

    url, _ = _gl(f"/projects/{project_id}/remote_mirrors")
    payload = {
        "url": mirror_url,
        "enabled": True,
        "only_protected_branches": True,   # ← prevents temp sync branches leaking to GitHub
        "keep_divergent_refs": True,
    }

    resp = session.post(url, json=payload, timeout=15)
    _raise(resp, "enable push mirror")
    return resp.json()

# ---------------------------------------------------------------------------
# Step 3b — Protect the default branch
# ---------------------------------------------------------------------------

def protect_default_branch(project_id: int, branch: str) -> None:
    """
    Mark the default branch (e.g. 'main') as protected in GitLab.
    This is required for two reasons:
      1. Push mirror is set to only_protected_branches=True — if the default
         branch is not protected, it won't be mirrored to GitHub at all.
      2. Prevents accidental force-pushes to the main branch.

    Protection rules set:
      - Maintainers can push directly
      - Developers can merge (via MR)
      - No one can force-push
    """
    # First check if protection already exists (GitLab auto-protects 'main' on some versions)
    check_url, _ = _gl(f"/projects/{project_id}/protected_branches/{branch}")
    check_resp = session.get(check_url, timeout=15)

    if check_resp.status_code == 200:
        # Already protected — nothing to do
        return

    url, _ = _gl(f"/projects/{project_id}/protected_branches")
    resp = session.post(url, json={
        "name":                      branch,
        "push_access_level":         40,   # 40 = Maintainer
        "merge_access_level":        30,   # 30 = Developer
        "allow_force_push":          False,
    }, timeout=15)
    _raise(resp, f"protect branch '{branch}'")


# ---------------------------------------------------------------------------
# Step 4 — Deploy .gitlab-ci.yml using the template include approach
# ---------------------------------------------------------------------------

def deploy_ci_file(project: dict) -> None:
    """
    Push a minimal .gitlab-ci.yml into the new project.
    This file simply includes the pipeline from your central template project.
    All new projects reference the same template — update once, all projects benefit.
    """
    if not TEMPLATE_PROJECT_ID:
        raise RuntimeError(
            "TEMPLATE_PROJECT_ID is not set in config.py. "
            "Create the template project first and paste its ID into config.py."
        )

    ci_content = f"""# Auto-generated by GitLab Provisioner
# DO NOT EDIT THIS FILE MANUALLY.
# The actual pipeline is maintained centrally in the sync-templates project.
# To update the pipeline for ALL projects, edit the template project instead.

include:
  - project: '{_get_template_project_path()}'
    ref: '{TEMPLATE_PROJECT_REF}'
    file: '/.gitlab-ci.yml'
"""

    project_id = project["id"]
    default_branch = project.get("default_branch") or "main"

    # Check if file already exists (in case of re-runs)
    check_url, _ = _gl(f"/projects/{project_id}/repository/files/.gitlab-ci.yml?ref={default_branch}")
    check_resp = session.get(check_url, timeout=15)

    file_url, _ = _gl(f"/projects/{project_id}/repository/files/.gitlab-ci.yml")
    payload = {
        "branch": default_branch,
        "content": ci_content,
        "commit_message": "chore: add GitLab CI pipeline (auto-provisioned)",
        "author_name": GIT_SYNC_USER,
        "author_email": GIT_SYNC_EMAIL,
    }

    if check_resp.status_code == 200:
        # File exists — update it
        resp = session.put(file_url, json=payload, timeout=15)
        _raise(resp, "update .gitlab-ci.yml")
    else:
        # File does not exist — create it
        resp = session.post(file_url, json=payload, timeout=15)
        _raise(resp, "create .gitlab-ci.yml")


def _get_template_project_path() -> str:
    """Resolve the template project's full path (e.g. 'infra/sync-templates') from its ID."""
    url, _ = _gl(f"/projects/{TEMPLATE_PROJECT_ID}")
    resp = session.get(url, timeout=15)
    _raise(resp, "fetch template project path")
    return resp.json()["path_with_namespace"]


# ---------------------------------------------------------------------------
# Step 5 — Create all CI/CD variables
# ---------------------------------------------------------------------------

# Variables that are the same for every project.
# GITHUB_REPO is intentionally NOT here — it is set per-project in the next function.
FIXED_VARIABLES = [
    # Sensitive tokens — Protected + Masked (matches your existing project config)
    {"key": "GITHUB_PAT",          "value": GITHUB_PAT,          "masked": True,  "protected": True},
    {"key": "GITLAB_PAT",          "value": GITLAB_PAT,          "masked": True,  "protected": True},
    # Identity + pipeline settings — not masked, not protected
    {"key": "GIT_SYNC_USER",       "value": GIT_SYNC_USER,       "masked": False, "protected": False},
    {"key": "GIT_SYNC_EMAIL",      "value": GIT_SYNC_EMAIL,      "masked": False, "protected": False},
    {"key": "SYNC_BRANCH_PREFIX",  "value": SYNC_BRANCH_PREFIX,  "masked": False, "protected": False},
    {"key": "SYNC_SOURCE_BRANCH",  "value": SYNC_SOURCE_BRANCH,  "masked": False, "protected": False},
    {"key": "GITLAB_RUNNER_TAG",   "value": GITLAB_RUNNER_TAG,   "masked": False, "protected": False},
]


def create_ci_variables(project_id: int, github_repo_url: str) -> list[str]:
    """
    Create all CI/CD variables for the project.
    Returns a list of variable keys that were successfully created.
    """
    all_vars = FIXED_VARIABLES + [
        {
            "key": "GITHUB_REPO",
            "value": github_repo_url,   # e.g. https://github.com/org/repo.git
            "masked": False,
            "protected": False,
        }
    ]

    created = []
    for var in all_vars:
        url, _ = _gl(f"/projects/{project_id}/variables")
        resp = session.post(url, json={
            "key":             var["key"],
            "value":           var["value"],
            "masked":          var["masked"],
            "protected":       var["protected"],
            "variable_type":   "env_var",
        }, timeout=15)

        if resp.status_code == 400 and "already been taken" in (resp.text or ""):
            # Variable already exists — update it instead
            put_url, _ = _gl(f"/projects/{project_id}/variables/{var['key']}")
            resp = session.put(put_url, json={
                "value":    var["value"],
                "masked":   var["masked"],
                "protected": var["protected"],
            }, timeout=15)
            _raise(resp, f"update variable {var['key']}")
        else:
            _raise(resp, f"create variable {var['key']}")

        created.append(var["key"])

    return created


# ---------------------------------------------------------------------------
# Step 6 — Configure project settings
# ---------------------------------------------------------------------------

def configure_project_settings(project_id: int) -> None:
    """
    Apply recommended settings to the project:
    - Only maintainers can push to default branch (protected)
    - Merge requests enabled
    - Pipelines enabled
    """
    url, _ = _gl(f"/projects/{project_id}")
    resp = session.put(url, json={
        "only_allow_merge_if_pipeline_succeeds": False,
        "remove_source_branch_after_merge": True,
        "shared_runners_enabled": True,
    }, timeout=15)
    _raise(resp, "configure project settings")


# ---------------------------------------------------------------------------
# Master orchestrator — runs all steps in order
# ---------------------------------------------------------------------------

def provision(
    github_url: str,
    group_id: int,
    progress_callback=None,
) -> dict:
    """
    Full provisioning flow. Calls progress_callback(step, total, message) at each step.
    Project name is always derived from the GitHub repo name for consistency.
    Returns {"project_url": "...", "project_id": ..., "steps_completed": [...]}
    """
    def progress(step, msg):
        if progress_callback:
            progress_callback(step, 7, msg)

    steps_completed = []

    # ── Step 0: Validate ──────────────────────────────────────────────────
    progress(0, "Validating GitHub repository access...")
    repo_info = validate_github_repo(github_url)
    steps_completed.append("GitHub repo validated")

    # Project name always == GitHub repo name (enforced for consistency)
    project_name = repo_info["repo"]

    # Derive the clean GitHub HTTPS URL for the CI variable
    github_repo_var_value = f"https://github.com/{repo_info['full_name']}.git"

    # ── Step 1: Create project ────────────────────────────────────────────
    progress(1, f"Creating GitLab project '{project_name}' and importing from GitHub (this may take up to 60s)...")
    project = create_project(repo_info, group_id, project_name)
    steps_completed.append(f"Project created (ID: {project['id']})")

    # ── Step 2: Push mirror ───────────────────────────────────────────────
    progress(2, "Enabling push mirroring to GitHub (protected branches only)...")
    enable_push_mirror(project["id"], repo_info["full_name"])
    steps_completed.append("Push mirror enabled (protected branches only)")

    # ── Step 3: Protect default branch ───────────────────────────────────
    default_branch = project.get("default_branch") or "main"
    progress(3, f"Protecting default branch '{default_branch}'...")
    protect_default_branch(project["id"], default_branch)
    steps_completed.append(f"Branch '{default_branch}' protected (pushes to GitHub, blocks force-push)")

    # ── Step 4: CI/CD pipeline file ───────────────────────────────────────
    progress(4, "Deploying .gitlab-ci.yml (template include)...")
    deploy_ci_file(project)
    steps_completed.append(".gitlab-ci.yml deployed")

    # ── Step 5: CI/CD variables ───────────────────────────────────────────
    progress(5, "Creating CI/CD variables...")
    created_vars = create_ci_variables(project["id"], github_repo_var_value)
    steps_completed.append(f"Variables created: {', '.join(created_vars)}")

    # ── Step 6: Project settings ──────────────────────────────────────────
    progress(6, "Applying project settings...")
    configure_project_settings(project["id"])
    steps_completed.append("Project settings configured")

    progress(7, "Done!")

    return {
        "project_url":      project["web_url"],
        "project_id":       project["id"],
        "project_path":     project["path_with_namespace"],
        "default_branch":   default_branch,
        "steps_completed":  steps_completed,
        "github_repo":      repo_info["full_name"],
    }
