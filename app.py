"""
app.py — GitLab Provisioner Web UI
====================================
A simple internal web app. Run with:
    python app.py
Then open http://YOUR-SERVER-IP:5001 in any browser on the network.
"""

import threading
import uuid
from flask import Flask, render_template_string, request, jsonify
from config import PROVISIONER_HOST, PROVISIONER_PORT, DEFAULT_GROUP_PATH
import provisioner

app = Flask(__name__)

# In-memory job store — tracks ongoing/completed provisioning runs
# { job_id: { "status": "running"|"done"|"error", "steps": [...], "result": {...}, "error": "" } }
jobs: dict = {}
jobs_lock = threading.Lock()


# ---------------------------------------------------------------------------
# HTML template — single-file, no external dependencies except the server
# ---------------------------------------------------------------------------

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GitLab Project Provisioner</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f4f5f7; color: #172b4d; min-height: 100vh; padding: 40px 20px; }
  .card { background: #fff; border-radius: 12px; box-shadow: 0 1px 4px rgba(0,0,0,.12); max-width: 680px; margin: 0 auto; }
  .card-header { padding: 28px 32px 20px; border-bottom: 1px solid #ebecf0; }
  .card-header h1 { font-size: 20px; font-weight: 600; color: #172b4d; }
  .card-header p { margin-top: 6px; font-size: 14px; color: #5e6c84; }
  .card-body { padding: 28px 32px; }
  label { display: block; font-size: 13px; font-weight: 600; color: #172b4d; margin-bottom: 6px; margin-top: 20px; }
  label:first-of-type { margin-top: 0; }
  input[type=text], select { width: 100%; padding: 10px 12px; border: 2px solid #dfe1e6; border-radius: 6px; font-size: 14px; color: #172b4d; transition: border-color .15s; outline: none; background: #fafbfc; }
  input[type=text]:focus, select:focus { border-color: #0052cc; background: #fff; }
  .hint { font-size: 12px; color: #5e6c84; margin-top: 4px; }
  .btn { display: inline-flex; align-items: center; gap: 8px; margin-top: 24px; padding: 10px 22px; background: #0052cc; color: #fff; border: none; border-radius: 6px; font-size: 14px; font-weight: 600; cursor: pointer; transition: background .15s; }
  .btn:hover { background: #0065ff; }
  .btn:disabled { background: #b3d4ff; cursor: not-allowed; }
  #progress-panel { display: none; margin-top: 28px; border-top: 1px solid #ebecf0; padding-top: 24px; }
  .step { display: flex; align-items: flex-start; gap: 10px; padding: 8px 0; font-size: 14px; }
  .step-icon { width: 20px; height: 20px; border-radius: 50%; flex-shrink: 0; margin-top: 1px; display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; }
  .step-icon.pending  { background: #dfe1e6; color: #5e6c84; }
  .step-icon.running  { background: #deebff; color: #0052cc; animation: pulse 1s infinite; }
  .step-icon.done     { background: #e3fcef; color: #006644; }
  .step-icon.error    { background: #ffebe6; color: #bf2600; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.5} }
  .step-text { color: #172b4d; line-height: 1.5; }
  .step-text.muted { color: #5e6c84; }
  .result-box { background: #e3fcef; border: 1px solid #abf5d1; border-radius: 8px; padding: 16px 20px; margin-top: 16px; }
  .result-box h3 { font-size: 15px; color: #006644; margin-bottom: 10px; }
  .result-box a { color: #0052cc; font-weight: 600; word-break: break-all; }
  .result-box .meta { font-size: 12px; color: #5e6c84; margin-top: 6px; }
  .error-box { background: #ffebe6; border: 1px solid #ffbdad; border-radius: 8px; padding: 16px 20px; margin-top: 16px; }
  .error-box h3 { font-size: 15px; color: #bf2600; margin-bottom: 8px; }
  .error-box pre { font-size: 12px; color: #5e6c84; white-space: pre-wrap; word-break: break-word; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 20px; font-size: 11px; font-weight: 600; background: #deebff; color: #0747a6; margin-left: 6px; vertical-align: middle; }
</style>
</head>
<body>
<div class="card">
  <div class="card-header">
    <h1>GitLab Project Provisioner</h1>
    <p>Creates a new GitLab project from a GitHub repo — with push mirroring, CI pipeline, and all variables — in one click.</p>
  </div>
  <div class="card-body">
    <label for="github_url">GitHub Repository URL</label>
    <input type="text" id="github_url" placeholder="https://github.com/client-org/repo-name" autocomplete="off">
    <p class="hint">Full URL of the GitHub repo to import. Your GitHub PAT must have access to it.</p>

    <label for="group_id">Target GitLab Group</label>
    <select id="group_id">
      <option value="">Loading groups…</option>
    </select>
    <p class="hint">The project will be created inside this group.</p>

    <label for="project_name">GitLab Project Name</label>
    <input type="text" id="project_name" placeholder="Auto-filled from repo name" autocomplete="off">
    <p class="hint">Leave blank to use the GitHub repo name as-is.</p>

    <button class="btn" id="provision-btn" onclick="startProvision()">
      <span>Provision Project</span>
    </button>

    <div id="progress-panel">
      <div id="steps-list"></div>
      <div id="result-area"></div>
    </div>
  </div>
</div>

<script>
  let pollTimer = null;

  // Auto-fill project name from GitHub URL
  document.getElementById('github_url').addEventListener('input', function() {
    const url = this.value.trim();
    const match = url.match(/github\\.com\\/[^\\/]+\\/([^\\/\\.]+)/);
    const nameField = document.getElementById('project_name');
    if (match && !nameField._userEdited) {
      nameField.value = match[1];
    }
  });
  document.getElementById('project_name').addEventListener('input', function() {
    this._userEdited = this.value.trim() !== '';
  });

  // Load groups on page load
  window.addEventListener('load', loadGroups);

  function loadGroups() {
    fetch('/api/groups')
      .then(r => r.json())
      .then(groups => {
        const sel = document.getElementById('group_id');
        sel.innerHTML = '';
        if (!groups.length) {
          sel.innerHTML = '<option value="">No groups found — create one in GitLab first</option>';
          return;
        }
        groups.forEach(g => {
          const opt = document.createElement('option');
          opt.value = g.id;
          opt.textContent = g.full_path;
          if (g.full_path === '{{ default_group }}') opt.selected = true;
          sel.appendChild(opt);
        });
      })
      .catch(() => {
        document.getElementById('group_id').innerHTML = '<option value="">Error loading groups — check config.py</option>';
      });
  }

  function startProvision() {
    const githubUrl   = document.getElementById('github_url').value.trim();
    const groupId     = document.getElementById('group_id').value;
    const projectName = document.getElementById('project_name').value.trim();

    if (!githubUrl) { alert('Please enter a GitHub repository URL.'); return; }
    if (!groupId)   { alert('Please select a target GitLab group.'); return; }

    document.getElementById('provision-btn').disabled = true;
    document.getElementById('progress-panel').style.display = 'block';
    document.getElementById('steps-list').innerHTML = '';
    document.getElementById('result-area').innerHTML = '';

    appendStep('init', 'running', 'Starting provisioner…');

    fetch('/api/provision', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ github_url: githubUrl, group_id: parseInt(groupId), project_name: projectName }),
    })
    .then(r => r.json())
    .then(data => {
      if (data.error) {
        updateStep('init', 'error', data.error);
        showError(data.error);
        document.getElementById('provision-btn').disabled = false;
        return;
      }
      // Start polling for progress
      pollProgress(data.job_id);
    })
    .catch(err => {
      updateStep('init', 'error', 'Failed to start: ' + err);
      document.getElementById('provision-btn').disabled = false;
    });
  }

  function pollProgress(jobId) {
    pollTimer = setInterval(() => {
      fetch('/api/job/' + jobId)
        .then(r => r.json())
        .then(data => {
          // Sync the displayed steps
          const list = document.getElementById('steps-list');
          list.innerHTML = '';
          data.steps.forEach((s, i) => {
            const isLast = i === data.steps.length - 1;
            const status = data.status === 'running' && isLast ? 'running' : 'done';
            appendStep('s'+i, status, s);
          });

          if (data.status === 'done') {
            clearInterval(pollTimer);
            appendStep('final', 'done', 'Provisioning complete!');
            showResult(data.result);
            document.getElementById('provision-btn').disabled = false;
          } else if (data.status === 'error') {
            clearInterval(pollTimer);
            appendStep('err', 'error', 'Failed: ' + data.error);
            showError(data.error);
            document.getElementById('provision-btn').disabled = false;
          }
        });
    }, 2000);
  }

  function appendStep(id, status, text) {
    const list = document.getElementById('steps-list');
    const icons = { pending: '·', running: '…', done: '✓', error: '✗' };
    const div = document.createElement('div');
    div.className = 'step';
    div.id = 'step-' + id;
    div.innerHTML = `
      <div class="step-icon ${status}">${icons[status]}</div>
      <div class="step-text ${status === 'pending' ? 'muted' : ''}">${escHtml(text)}</div>`;
    list.appendChild(div);
  }

  function updateStep(id, status, text) {
    const el = document.getElementById('step-' + id);
    if (el) el.remove();
    appendStep(id, status, text);
  }

  function showResult(result) {
    document.getElementById('result-area').innerHTML = `
      <div class="result-box">
        <h3>✓ Project ready</h3>
        <a href="${escHtml(result.project_url)}" target="_blank">${escHtml(result.project_url)}</a>
        <div class="meta">
          GitLab path: <strong>${escHtml(result.project_path)}</strong><br>
          GitHub repo: <strong>${escHtml(result.github_repo)}</strong><br>
          Default branch: <strong>${escHtml(result.default_branch)}</strong><br>
          Project ID: <strong>${result.project_id}</strong>
        </div>
        <div class="meta" style="margin-top:10px;">
          <strong>Steps completed:</strong><br>
          ${result.steps_completed.map((s,i) => `${i+1}. ${escHtml(s)}`).join('<br>')}
        </div>
      </div>`;
  }

  function showError(msg) {
    document.getElementById('result-area').innerHTML = `
      <div class="error-box">
        <h3>Provisioning failed</h3>
        <pre>${escHtml(msg)}</pre>
      </div>`;
  }

  function escHtml(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template_string(HTML, default_group=DEFAULT_GROUP_PATH)


@app.route("/api/groups")
def api_groups():
    try:
        groups = provisioner.get_all_groups()
        return jsonify(groups)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/provision", methods=["POST"])
def api_provision():
    data = request.get_json()
    github_url   = (data.get("github_url") or "").strip()
    group_id     = data.get("group_id")
    project_name = (data.get("project_name") or "").strip()

    if not github_url:
        return jsonify({"error": "github_url is required"}), 400
    if not group_id:
        return jsonify({"error": "group_id is required"}), 400

    # If no name given, derive from the URL
    if not project_name:
        project_name = github_url.rstrip("/").rstrip(".git").split("/")[-1]

    job_id = str(uuid.uuid4())
    with jobs_lock:
        jobs[job_id] = {"status": "running", "steps": [], "result": None, "error": ""}

    def run():
        def on_progress(step, total, msg):
            with jobs_lock:
                jobs[job_id]["steps"].append(msg)

        try:
            result = provisioner.provision(
                github_url=github_url,
                group_id=group_id,
                project_name=project_name,
                progress_callback=on_progress,
            )
            with jobs_lock:
                jobs[job_id]["status"] = "done"
                jobs[job_id]["result"] = result
        except Exception as e:
            with jobs_lock:
                jobs[job_id]["status"] = "error"
                jobs[job_id]["error"] = str(e)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/job/<job_id>")
def api_job(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"\n  GitLab Provisioner is running.")
    print(f"  Open http://YOUR-SERVER-IP:{PROVISIONER_PORT} in your browser.\n")
    app.run(host=PROVISIONER_HOST, port=PROVISIONER_PORT, debug=False, threaded=True)
