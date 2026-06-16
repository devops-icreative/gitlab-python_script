# =============================================================================
# GITLAB PROVISIONER — CONFIGURATION
# =============================================================================
# Fill in every value marked with  ← FILL THIS IN  before starting the app.
# After editing this file, restart the service:
#   sudo systemctl restart gitlab-provisioner
# =============================================================================

# --- GitLab connection ---
GITLAB_URL      = "http://gitlab.local"          # ← Change to your final domain when hosted
GITLAB_PAT      = "glpat-XXXXXXXXXXXXXXXXXXXX"   # ← FILL THIS IN (your GitLab personal access token, needs api + write_repository scope)

# --- GitHub credentials ---
GITHUB_PAT      = "ghp_XXXXXXXXXXXXXXXXXXXX"     # ← FILL THIS IN (your GitHub personal access token, needs repo scope)

# --- Git identity used by the sync runner ---
GIT_SYNC_USER   = "Sync Bot"                     # ← FILL THIS IN (e.g. "GitLab Sync Bot")
GIT_SYNC_EMAIL  = "sync@yourcompany.com"         # ← FILL THIS IN (e.g. "gitlab-sync@yourcompany.com")

# --- Sync pipeline settings ---
SYNC_BRANCH_PREFIX = "github-sync"               # ← Change only if you use a different prefix (default: github-sync)
GITLAB_RUNNER_TAG  = "sync"                      # ← FILL THIS IN (the tag on your GitLab runner that runs sync jobs)

# --- Central CI template project ---
# After you manually create the template project in GitLab (see SETUP_GUIDE.md Step 1),
# paste its numeric project ID here.
# Find it: GitLab project page → Settings → General → Project ID (shown at the top)
TEMPLATE_PROJECT_ID = ""                         # ← FILL THIS IN (e.g. "3")
TEMPLATE_PROJECT_REF = "main"                    # ← Branch in the template project where .gitlab-ci.yml lives

# --- Web UI settings ---
# The provisioner web UI will run on this port.
# Make sure this port is open in your firewall (or only accessible internally).
PROVISIONER_PORT = 5001
PROVISIONER_HOST = "0.0.0.0"                     # 0.0.0.0 = accessible from any machine on the network

# --- GitLab group structure ---
# When a new project is created, it goes into a group.
# The UI shows a dropdown of all existing groups. This is the default pre-selected one.
DEFAULT_GROUP_PATH = ""                          # ← FILL THIS IN (e.g. "clients" — the top-level group slug)
