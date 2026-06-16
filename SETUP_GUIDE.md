# GitLab Provisioner — Complete Setup Guide
==========================================

This guide walks you through everything: creating the template project in GitLab,
deploying the provisioner on your server, and doing the first test run.
Follow every step in order. Do not skip.

---

## PART 1 — Create the Central Template Project in GitLab
(You do this ONCE. This is the project that holds your .gitlab-ci.yml.)

### 1.1 — Create a new GitLab project for the template

1. Open http://gitlab.local in your browser and log in as admin.
2. Click the **"+"** button in the top navigation bar → click **"New project"**.
3. Click **"Create blank project"**.
4. Fill in:
   - **Project name:** `sync-templates`  (you can use any name, but be consistent)
   - **Project URL:** Select your infrastructure group (e.g. "infra" or "internal") from the
     namespace dropdown. Do NOT put this inside a client group.
   - **Visibility Level:** Private
   - **Initialize repository with a README:** ✓ Check this box (required — creates the main branch)
5. Click **"Create project"**.
6. You are now inside the new project. Look at the URL — it will be something like:
     http://gitlab.local/infra/sync-templates
   Note this path — you'll need it.

### 1.2 — Note the Project ID

1. Inside the `sync-templates` project, go to **Settings** → **General**.
2. At the very top, you'll see: **Project ID: 3** (the number will be different for you).
3. Copy that number. You'll paste it into `config.py` as `TEMPLATE_PROJECT_ID`.

### 1.3 — Add your .gitlab-ci.yml to the template project

1. Inside the `sync-templates` project, click **"+"** (next to the branch name, in the file browser)
   → click **"New file"**.
2. In the **"File name"** box at the top, type exactly: `.gitlab-ci.yml`
3. In the large content box, paste your current working .gitlab-ci.yml content
   (copy it from your existing test project).
4. Scroll down. Set **"Commit message"** to: `initial sync pipeline template`
5. Make sure **"Target Branch"** is `main`.
6. Click **"Commit changes"**.

Your template project is now ready. Every new project the provisioner creates will
reference this file rather than having its own copy.

To update the pipeline for ALL projects in the future:
  → Just edit .gitlab-ci.yml in sync-templates → commit → all projects pick it up automatically.

---

## PART 2 — Deploy the Provisioner on Your Server

Run all commands below on your GitLab server via SSH.

### 2.1 — Copy the provisioner files to the server

From your laptop, run:

    scp -r /path/to/gitlab-provisioner ubuntu@YOUR-SERVER-IP:/tmp/gitlab-provisioner

Or if you prefer, create the files directly on the server using nano/vim.

### 2.2 — Move files into place

    sudo mv /tmp/gitlab-provisioner /opt/gitlab-provisioner
    sudo chown -R ubuntu:ubuntu /opt/gitlab-provisioner

(Replace "ubuntu" with your actual server username if different.)

### 2.3 — Create a Python virtual environment and install dependencies

    cd /opt/gitlab-provisioner
    python3 -m venv venv
    ./venv/bin/pip install --upgrade pip
    ./venv/bin/pip install -r requirements.txt

### 2.4 — Fill in config.py

    nano /opt/gitlab-provisioner/config.py

Fill in every value marked with  ← FILL THIS IN:

  - GITLAB_URL      → your final server URL (e.g. https://gitlab.yourcompany.com)
                       For now during testing: http://gitlab.local
  - GITLAB_PAT      → your GitLab personal access token
                       How to get one: GitLab → top-right avatar → Edit Profile
                       → Access Tokens → Add new token
                       → Name: "provisioner", Scopes: check "api" and "write_repository"
                       → Click "Create personal access token" → COPY THE TOKEN NOW (shown only once)
  - GITHUB_PAT      → your GitHub personal access token (the same one in your CI variables)
  - GIT_SYNC_USER   → same value as in your existing GitLab CI variables
  - GIT_SYNC_EMAIL  → same value as in your existing GitLab CI variables
  - SYNC_BRANCH_PREFIX → same value as in your existing GitLab CI variables (e.g. "github-sync")
  - GITLAB_RUNNER_TAG  → the tag on your runner that runs sync jobs (e.g. "sync")
  - TEMPLATE_PROJECT_ID → the Project ID you noted in Step 1.2 (e.g. "3")
  - DEFAULT_GROUP_PATH  → the group slug you use most often (e.g. "clients")

Save and close: Ctrl+X → Y → Enter.

### 2.5 — Test it manually before setting up the service

    cd /opt/gitlab-provisioner
    ./venv/bin/python app.py

You should see:
    GitLab Provisioner is running.
    Open http://YOUR-SERVER-IP:5001 in your browser.

Open that URL from your laptop browser and confirm the page loads.
Press Ctrl+C to stop it after confirming.

### 2.6 — Install as a systemd service (auto-starts on reboot)

    sudo cp /opt/gitlab-provisioner/gitlab-provisioner.service /etc/systemd/system/
    sudo nano /etc/systemd/system/gitlab-provisioner.service

In the file, update:
  - Line "User=ubuntu" → change "ubuntu" to your actual server username
  - Line "WorkingDirectory" and "ExecStart" paths should already be /opt/gitlab-provisioner — leave them.

Save and close: Ctrl+X → Y → Enter.

    sudo systemctl daemon-reload
    sudo systemctl enable gitlab-provisioner
    sudo systemctl start gitlab-provisioner

Check it's running:

    sudo systemctl status gitlab-provisioner

You should see "active (running)" in green. If you see an error, check logs:

    journalctl -u gitlab-provisioner -n 50

### 2.7 — Open port 5001 on the firewall (if UFW is active)

    sudo ufw allow 5001/tcp comment "GitLab Provisioner"
    sudo ufw status

---

## PART 3 — First Test Run

### 3.1 — Open the web UI

From any machine on your network, open:
    http://YOUR-SERVER-IP:5001

(After you set up SSL and your real domain, you can put this behind a subdomain like
http://provision.gitlab.yourcompany.com — just update GITLAB_URL and the nginx config.)

### 3.2 — Provision a test project

1. In the **"GitHub Repository URL"** field, paste a GitHub repo you have PAT access to.
2. Select a **target group** from the dropdown.
3. The **project name** auto-fills from the repo name — change it if you want.
4. Click **"Provision Project"**.
5. Watch the progress steps appear in real time.

The full process takes 30–90 seconds depending on repo size (most of that is GitLab importing from GitHub).

### 3.3 — Verify in GitLab after provisioning

Go to http://gitlab.local and navigate to the new project. Check:

☐ Project was created inside the correct group
☐ Code is there (branches match GitHub)
☐ Settings → Repository → Mirroring repositories → shows GitHub push mirror as enabled
☐ Settings → CI/CD → Variables → shows all 7 variables (GITHUB_PAT, GITLAB_PAT, GIT_SYNC_USER,
   GIT_SYNC_EMAIL, SYNC_BRANCH_PREFIX, GITLAB_RUNNER_TAG, GITHUB_REPO)
☐ The .gitlab-ci.yml file in the repo contains "include:" pointing to sync-templates
☐ Run a manual pipeline — it should execute via the sync runner

---

## PART 4 — Giving Access to Your Manager / Others

The provisioner is protected only by network access (only people on your internal network
can reach port 5001). For now during local testing that's fine.

When you move to a proper server:
  - Keep the provisioner on a private/internal network port, OR
  - Add HTTP Basic Auth (ask me and I'll add it — it's ~10 lines in app.py), OR
  - Put it behind your company VPN

No one needs GitLab credentials, GitHub credentials, or terminal access.
They just open the URL, paste a GitHub repo link, pick a group, and click Provision.

---

## PART 5 — Useful Commands for Ongoing Management

Restart after editing config.py:
    sudo systemctl restart gitlab-provisioner

View live logs:
    journalctl -u gitlab-provisioner -f

Stop the service:
    sudo systemctl stop gitlab-provisioner

Update the provisioner files:
    sudo systemctl stop gitlab-provisioner
    # copy new files to /opt/gitlab-provisioner
    sudo systemctl start gitlab-provisioner

---

## TROUBLESHOOTING

**"GitLab API error [create project] 403"**
→ Your GITLAB_PAT doesn't have "api" scope. Regenerate it with api + write_repository.

**"GitHub repo not found or not accessible"**
→ Your GITHUB_PAT doesn't have access to that repo. Check the repo exists and the PAT has "repo" scope.

**"Import timed out after 5 minutes"**
→ The repo is very large, or GitLab's Sidekiq background workers are slow.
  Check: Admin Area → Monitoring → Background Jobs.

**"TEMPLATE_PROJECT_ID is not set"**
→ You forgot to paste the template project ID into config.py. See Part 1, Step 1.2.

**The web UI shows "Error loading groups"**
→ Check that GITLAB_URL and GITLAB_PAT are correctly set in config.py.
  Test manually: curl -H "PRIVATE-TOKEN: YOUR_PAT" http://gitlab.local/api/v4/groups

**Port 5001 not accessible from another machine**
→ Run: sudo ufw allow 5001/tcp  (see Step 2.7)
