"""Generate the demo notebooks for jupyterlab/jupyterlab#20372.

Run from the demo folder with the demo venv:
    .venv\\Scripts\\python.exe tools\\build_notebooks.py

Writes:
    loop.ipynb                    the issue's reproduction notebook (for a manual browser run)
    session_identity_demo.ipynb   an executable, self-contained demonstration
"""
import pathlib

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

HERE = pathlib.Path(__file__).resolve().parent.parent
PY_KERNEL = {"display_name": "Python 3 (ipykernel)", "language": "python", "name": "python3"}


def write(name, cells):
    nb = new_notebook(cells=cells, metadata={"kernelspec": PY_KERNEL, "language_info": {"name": "python"}})
    nbformat.validate(nb)
    nbformat.write(nb, HERE / name)
    print("wrote", HERE / name)


# ---------------------------------------------------------------------------
# loop.ipynb: the two cells from the issue, with the loop bounded to 10 minutes
# ---------------------------------------------------------------------------
write("loop.ipynb", [
    new_markdown_cell(
        "# loop.ipynb (from jupyterlab/jupyterlab#20372)\n\n"
        "The two cells from the issue's reproduction. The issue uses `while True`; here the loop stops on its own "
        "after 10 minutes so a forgotten kernel cannot run forever.\n\n"
        "Follow the steps in `README.md` (section *Manual browser reproduction*)."
    ),
    new_code_cell(
        "import os, time\n"
        "for _ in range(1200):  # the issue uses `while True`; bounded to 10 minutes here\n"
        "    with open(\"heartbeat.txt\", \"w\") as f:\n"
        "        f.write(f\"pid {os.getpid()} at {time.time():.1f}\")\n"
        "    time.sleep(0.5)"
    ),
    new_code_cell(
        "import os, time\n"
        "print(\"this kernel: pid\", os.getpid())\n"
        "print(\"loop:\", open(\"heartbeat.txt\").read())\n"
        "time.sleep(2)\n"
        "print(\"loop:\", open(\"heartbeat.txt\").read())"
    ),
])

# ---------------------------------------------------------------------------
# session_identity_demo.ipynb
# ---------------------------------------------------------------------------
cells = []
md = lambda text: cells.append(new_markdown_cell(text))
code = lambda text: cells.append(new_code_cell(text))

md(r'''# Reloading a notebook can connect it to another kernel (jupyterlab#20372)

**Issue:** [jupyterlab/jupyterlab#20372](https://github.com/jupyterlab/jupyterlab/issues/20372). When the server has two sessions for one notebook, reloading the page can connect the notebook to the *other* session's kernel. Restart Kernel then restarts the wrong kernel and the code the notebook started keeps running.

This notebook reproduces that and compares three behaviours side by side:

| | Behaviour | Where it comes from |
|---|---|---|
| **Main** | JupyterLab 4.6.x today | `sessioncontext.tsx` at commit `29752fe` |
| **PR #20426** | Selecting a kernel reuses the session already on the path | [jupyterlab#20426](https://github.com/jupyterlab/jupyterlab/pull/20426) (another contributor) |
| **Proposal** | A reloaded notebook reconnects to the kernel it was using | Our design, described below. **Not implemented in JupyterLab yet.** |

### What is real and what is modelled

* **Real:** a Jupyter Server (started by this notebook on its own port), its sessions, its kernels, the kernel processes and the looping cell from the issue.
* **Modelled:** the JupyterLab front-end is not running. Each front-end step is a Python transcription of the TypeScript function linked next to it. It sends the same REST requests in the same order. The "page reload" is the front-end's `SessionContext._initialize()` running again with fresh state, which is what a reload does.

Everything runs locally. Clean-up at the end shuts down every kernel and the server. The looping cell is bounded to 2 minutes as a safety net.''')

md(r'''## 1. Start a private Jupyter Server

The server gets a random free port, a random token, its own root directory and its own runtime directory under `demo-run/`. This avoids touching any Jupyter server you already have running.''')

code(r'''import os, pathlib, posixpath, shutil, socket, subprocess, sys, time, uuid, warnings

# pyzmq warns once on Windows about the default asyncio loop; it does not affect the demo.
warnings.filterwarnings("ignore", message="Proactor event loop does not implement add_reader")

import nbformat
import requests
from IPython.display import Markdown, display
from jupyter_client import BlockingKernelClient

DEMO_DIR = pathlib.Path.cwd() / "demo-run"
ROOT = DEMO_DIR / "server-root"      # the server's root directory; loop.ipynb lives here
RUNTIME = DEMO_DIR / "runtime"       # kernel connection files
shutil.rmtree(DEMO_DIR, ignore_errors=True)
ROOT.mkdir(parents=True)
RUNTIME.mkdir()

NOTEBOOK = "loop.ipynb"              # the notebook path, as the server and the front-end see it
HEARTBEAT = ROOT / "heartbeat.txt"
LOOP_SECONDS = 120                   # safety bound; the issue uses `while True`

# The notebook from the issue, so the sessions refer to a real file.
nbformat.write(nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell("# see ../loop.ipynb")]), ROOT / NOTEBOOK)

def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]

PORT, TOKEN = free_port(), uuid.uuid4().hex
BASE = f"http://127.0.0.1:{PORT}"
HEADERS = {"Authorization": f"token {TOKEN}"}
server_log = open(DEMO_DIR / "server.log", "w")
server = subprocess.Popen(
    [sys.executable, "-m", "jupyter_server", "--no-browser",
     "--ServerApp.ip=127.0.0.1", f"--ServerApp.port={PORT}", "--ServerApp.port_retries=0",
     f"--IdentityProvider.token={TOKEN}", f"--ServerApp.root_dir={ROOT}"],
    env={**os.environ, "JUPYTER_RUNTIME_DIR": str(RUNTIME)},
    stdout=server_log, stderr=subprocess.STDOUT,
)

def api(method, path, **kwargs):
    response = requests.request(method, BASE + path, headers=HEADERS, timeout=60, **kwargs)
    response.raise_for_status()
    return response.json() if response.content else None

deadline = time.time() + 60
while True:
    try:
        status = api("GET", "/api/status")
        break
    except requests.RequestException:
        if server.poll() is not None or time.time() > deadline:
            raise RuntimeError("Jupyter Server did not start; see demo-run/server.log")
        time.sleep(0.5)

import jupyter_server, jupyter_client, ipykernel
print(f"Jupyter Server {jupyter_server.__version__} on port {PORT} (jupyter_client {jupyter_client.__version__}, ipykernel {ipykernel.__version__})")
print("server root:", ROOT)''')

md(r'''## 2. Helpers: kernels, the looping cell and the heartbeat

`start_cell` behaves like pressing Shift+Enter on the looping cell: it sends the code and returns once the kernel reports it is busy, without waiting for the cell to finish. `run_cell` runs a cell to completion and returns what it printed.

The looping cell is the first cell of the issue's `loop.ipynb`. It rewrites `heartbeat.txt` every 0.5 s with its process id and the time. `loop_is_running()` reads the file twice, 2 s apart. If the timestamp moved, the loop is still running.

**How to read the outputs:** a restarted kernel is a new process, so after Restart Kernel the notebook's pid always differs from the loop's pid. What shows whether the restart stopped the loop is the second `loop:` line. If its timestamp is later than the first, the loop is still running somewhere. The server reports a kernel that no client has connected to yet as `starting`.''')

code(r'''LOOP_CELL = f"""import os, time
for _ in range({int(LOOP_SECONDS / 0.5)}):  # the issue uses `while True`
    with open("heartbeat.txt", "w") as f:
        f.write(f"pid {{os.getpid()}} at {{time.time():.1f}}")
    time.sleep(0.5)
"""

CHECK_CELL = """import os, time
print("this kernel: pid", os.getpid())
print("loop:", open("heartbeat.txt").read())
time.sleep(2)
print("loop:", open("heartbeat.txt").read())
"""

def _client(kernel_id):
    client = BlockingKernelClient(connection_file=str(RUNTIME / f"kernel-{kernel_id}.json"))
    client.load_connection_file()
    # Without a kernel manager, the heartbeat channel can report "dead" before its first beat on a
    # slow kernel start. wait_for_ready still waits for a real kernel_info_reply.
    client.start_channels(hb=False)
    client.wait_for_ready(timeout=60)
    return client

def run_cell(kernel_id, source, timeout=60):
    """Run a cell to completion in the given kernel and return its printed output."""
    client, printed = _client(kernel_id), []
    def hook(msg):
        if msg["msg_type"] == "stream":
            printed.append(msg["content"]["text"])
    try:
        client.execute_interactive(source, timeout=timeout, output_hook=hook)
    finally:
        client.stop_channels()
    return "".join(printed)

def start_cell(kernel_id, source):
    """Start a long-running cell and return once the kernel is busy with it."""
    client = _client(kernel_id)
    try:
        msg_id = client.execute(source)
        while True:
            msg = client.get_iopub_msg(timeout=30)
            if (msg["parent_header"].get("msg_id") == msg_id and msg["msg_type"] == "status"
                    and msg["content"]["execution_state"] == "busy"):
                return
    finally:
        client.stop_channels()

def kernel_pid(kernel_id):
    return int(run_cell(kernel_id, "import os; print(os.getpid())"))

def read_heartbeat():
    for _ in range(50):
        try:
            text = HEARTBEAT.read_text()
            _, pid, _, timestamp = text.split()
            return int(pid), float(timestamp)
        except (FileNotFoundError, ValueError):
            time.sleep(0.1)  # the loop rewrites the file; retry a torn read
    raise RuntimeError("no heartbeat")

def loop_is_running():
    _, first = read_heartbeat()
    time.sleep(2)
    pid, second = read_heartbeat()
    return second > first, pid

def restart_kernel(kernel_id):
    """What Restart Kernel sends for the notebook's current kernel."""
    api("POST", f"/api/kernels/{kernel_id}/restart")

def reset_server():
    """Shut down every session and kernel and forget the heartbeat between scenarios."""
    for model in api("GET", "/api/sessions"):
        api("DELETE", f"/api/sessions/{model['id']}")
    for model in api("GET", "/api/kernels"):
        api("DELETE", f"/api/kernels/{model['id']}")
    HEARTBEAT.unlink(missing_ok=True)

def sessions_on_path():
    """The sessions the server lists for the notebook, in the server's order (creation order)."""
    return [model for model in api("GET", "/api/sessions") if model["path"] == NOTEBOOK]

def show_sessions(label, notebook_kernel=None):
    rows = ["| # | session | kernel | kernel state | used by the notebook |", "|---|---|---|---|---|"]
    for index, model in enumerate(sessions_on_path(), 1):
        mark = "**yes**" if model["kernel"]["id"] == notebook_kernel else ""
        rows.append(f"| {index} | `{model['id'][:8]}` | `{model['kernel']['id'][:8]}` | {model['kernel']['execution_state']} | {mark} |")
    display(Markdown(f"**{label}:** sessions the server lists for `{NOTEBOOK}`\n\n" + "\n".join(rows)))

RESULTS = []
print("helpers ready")''')

md(r'''## 3. The front-end steps, transcribed from JupyterLab

Each function below is the Python equivalent of the JupyterLab code linked in its docstring. The kernel selection step is subtle. The server reuses an existing session when asked to create one for a path it already has, so the front-end deliberately creates the session under a temporary UUID path and renames it to the notebook's path afterwards. That rename is how two sessions end up sharing `loop.ipynb`.''')

code(r'''SRC = "https://github.com/jupyterlab/jupyterlab/blob/29752fe1f6f0950a387afbe941dce5dcfbd60c0a/packages/apputils/src/sessioncontext.tsx"

def main_initialize(path):
    """SessionContext._initialize (SRC#L845-L868): connect to the FIRST session the server lists for the path.
    This runs when a notebook is opened and again after every page reload."""
    for model in api("GET", "/api/sessions"):
        if model["path"] == path:
            return model
    return None

def main_start_session(path, kernel_name="python3"):
    """SessionContext._changeKernel when the notebook has no session (SRC#L972-L1007):
    start a session under a temporary UUID path, then rename it to the notebook's path."""
    request_id = posixpath.join(posixpath.dirname(path), str(uuid.uuid4()))
    session = api("POST", "/api/sessions", json={
        "path": request_id, "type": "notebook", "name": posixpath.basename(path), "kernel": {"name": kernel_name}})
    api("PATCH", f"/api/sessions/{session['id']}", json={"path": path})                     # session.setPath(this._path)
    return api("PATCH", f"/api/sessions/{session['id']}", json={"name": posixpath.basename(path)})  # session.setName(this._name)

def open_notebook_normally(path):
    """Double-click in the file browser: connect to the path's session, or start one (_startIfNecessary)."""
    return main_initialize(path) or main_start_session(path)

def open_with_no_kernel(path):
    """Open With > Notebook (no kernel): kernelPreference {shouldStart: false, shouldReuse: false}
    (notebook-extension/src/index.ts#L1551-L1561). The front-end sends no session request."""
    return None

def pr20426_select_kernel(path, kernel_name="python3"):
    """PR #20426, _changeKernel with shouldReuse === false: refresh, and if the server lists a session
    for the path, change that session's kernel instead of starting a second session."""
    existing = main_initialize(path)  # refreshRunning() + _findPathSession(): the first session for the path
    if existing:
        return api("PATCH", f"/api/sessions/{existing['id']}", json={"kernel": {"name": kernel_name}})
    return main_start_session(path, kernel_name)

# --- Proposal: session identity affinity -------------------------------------------------------
# The front-end already stores restoration data for every open notebook (the layout restorer's state
# database), and ISessionContext.IKernelPreference already has an `id` field, "The id of an existing
# kernel" (SRC#L274-L277). The proposal keeps the id of the kernel the notebook is using in that
# restoration data and passes it as kernelPreference.id when the notebook is restored after a reload.
# _initialize then prefers the path's session that has that kernel, and falls back to today's
# choice when the kernel is gone. A remembered id that belongs to another path is ignored.
RESTORATION_STATE = {}   # stands in for the layout restorer's state database

def proposal_remember(path, session):
    RESTORATION_STATE[path] = session["kernel"]["id"]

def proposal_initialize(path):
    remembered = RESTORATION_STATE.get(path)
    candidates = [model for model in api("GET", "/api/sessions") if model["path"] == path]
    for model in candidates:
        if model["kernel"]["id"] == remembered:
            return model, "reconnected to the kernel the notebook used before the reload"
    if candidates:
        return candidates[0], "remembered kernel not found: fell back to the first session for the path (today's choice)"
    return None, "no session for the path"

print("front-end model ready")''')

md(r'''## Scenario 1. Main: reproduce the bug

These are the issue's steps 2 to 8. The notebook gets a kernel in step 4, starts the loop in step 5, and after the reload it is connected to the other session's kernel.''')

code(r'''reset_server()
session_a = open_notebook_normally(NOTEBOOK)            # step 2: open loop.ipynb, wait for Idle, close the tab
print("step 2  opened normally, then closed the tab:   session", session_a["id"][:8], "kernel", session_a["kernel"]["id"][:8])
open_with_no_kernel(NOTEBOOK)                           # step 3: Open With > Notebook (no kernel)
print("step 3  Open With > Notebook (no kernel):        no request is sent; the notebook has no kernel")
session_b = main_start_session(NOTEBOOK)                # step 4: No Kernel > Python 3 (ipykernel) > Select
print("step 4  selected Python 3:                        session", session_b["id"][:8], "kernel", session_b["kernel"]["id"][:8], "(a second session on the same path)")
used_before = session_b["kernel"]["id"]
loop_pid = kernel_pid(used_before)
start_cell(used_before, LOOP_CELL)                      # step 5: run the first cell
print("step 5  ran the looping cell in kernel", used_before[:8], "pid", loop_pid)
show_sessions("Before the reload", used_before)

after_reload = main_initialize(NOTEBOOK)                # step 6: reload the page
used_after = after_reload["kernel"]["id"]
print("step 6  page reload connected the notebook to kernel", used_after[:8])
restart_kernel(used_after)                              # step 7: Restart Kernel
print("step 7  Restart Kernel restarted kernel", used_after[:8])
print("step 8  second cell, run in the notebook's kernel:\n" + run_cell(used_after, CHECK_CELL))

running, heartbeat_pid = loop_is_running()
show_sessions("After the restart", used_after)
print(f"kernel before reload {used_before[:8]}, after reload {used_after[:8]}; the loop (pid {heartbeat_pid}) is",
      "STILL RUNNING" if running else "stopped")
assert used_after != used_before and running, "expected to reproduce the bug"
RESULTS.append(("Main", "issue steps 2-8", len(sessions_on_path()), used_after == used_before, not running))
print("\nBUG REPRODUCED: the reload switched kernels and Restart Kernel did not stop the notebook's loop.")''')

md(r'''## Scenario 2. PR #20426: the same steps, with the kernel selection reusing the path's session

In step 4, PR #20426 changes the kernel of the session that already exists for the path. On the server, changing a session's kernel starts a new kernel and shuts down the old one (`jupyter_server/services/sessions/handlers.py`, `SessionHandler.patch`). So there is still one session, and the reload finds it.''')

code(r'''reset_server()
session_a = open_notebook_normally(NOTEBOOK)            # step 2
old_kernel = session_a["kernel"]["id"]
open_with_no_kernel(NOTEBOOK)                           # step 3
session = pr20426_select_kernel(NOTEBOOK)               # step 4 with PR #20426
used_before = session["kernel"]["id"]
print("step 4  PR #20426 changed the kernel of session", session["id"][:8], "from", old_kernel[:8], "to", used_before[:8])
start_cell(used_before, LOOP_CELL)                      # step 5
show_sessions("Before the reload", used_before)

used_after = main_initialize(NOTEBOOK)["kernel"]["id"]  # step 6: PR #20426 keeps the reload logic
restart_kernel(used_after)                              # step 7
print("step 8  second cell:\n" + run_cell(used_after, CHECK_CELL))
running, _ = loop_is_running()
print(f"kernel before reload {used_before[:8]}, after reload {used_after[:8]}; the loop is", "STILL RUNNING" if running else "STOPPED")
assert used_after == used_before and not running
RESULTS.append(("PR #20426", "issue steps 2-8", len(sessions_on_path()), used_after == used_before, not running))
print("\nFIXED for the reported steps: one session, and Restart Kernel stopped the loop.")''')

md(r'''## Scenario 3. PR #20426 with two sessions that already exist

PR #20426 prevents new duplicate sessions. It does not change what a reload connects to. Its description says: *"A notebook that already has two sessions from an earlier run still has to have one of them shut down."* This is the state a server is in when a notebook got its second session before the fix was deployed, for example from JupyterLab 4.6.0 to 4.6.5, or from another client. The notebook below is using the newer session.''')

code(r'''def make_existing_duplicates():
    """Two sessions on the path; the notebook uses the second one and runs the loop there."""
    reset_server()
    first = main_start_session(NOTEBOOK)
    second = main_start_session(NOTEBOOK)
    start_cell(second["kernel"]["id"], LOOP_CELL)
    return first, second

first, second = make_existing_duplicates()
used_before = second["kernel"]["id"]
show_sessions("Before the reload", used_before)
used_after = main_initialize(NOTEBOOK)["kernel"]["id"]  # reload: unchanged by PR #20426
restart_kernel(used_after)
running, _ = loop_is_running()
print(f"kernel before reload {used_before[:8]}, after reload {used_after[:8]}; the loop is", "STILL RUNNING" if running else "STOPPED")
assert used_after != used_before and running
RESULTS.append(("PR #20426", "two sessions already exist", len(sessions_on_path()), used_after == used_before, not running))
print("\nNot covered by PR #20426: the reload still connected to the older session. The PR states this limitation.")''')

md(r'''## Scenario 4. Proposal: reconnect to the kernel the notebook was using

This uses the same starting state as scenario 3. The only difference is that the notebook's restoration data remembers the kernel it was using, as the proposal describes in section 3.''')

code(r'''first, second = make_existing_duplicates()
RESTORATION_STATE.clear()
proposal_remember(NOTEBOOK, second)                     # saved while the notebook was connected
used_before = second["kernel"]["id"]
show_sessions("Before the reload", used_before)
model, reason = proposal_initialize(NOTEBOOK)           # reload with the proposal
used_after = model["kernel"]["id"]
print("reload:", reason)
restart_kernel(used_after)
print("second cell:\n" + run_cell(used_after, CHECK_CELL))
running, _ = loop_is_running()
print(f"kernel before reload {used_before[:8]}, after reload {used_after[:8]}; the loop is", "STILL RUNNING" if running else "STOPPED")
assert used_after == used_before and not running
RESULTS.append(("Proposal", "two sessions already exist", len(sessions_on_path()), used_after == used_before, not running))
print("\nThe notebook kept its kernel across the reload, and Restart Kernel stopped its loop.")''')

md(r'''## Scenario 5. Proposal: safe fallbacks

A remembered kernel id is only a hint. It must never connect the notebook to something unexpected:

* **5a.** The remembered kernel was shut down, for example by another client or a server restart. The notebook falls back to today's choice, so nothing changes compared with main.
* **5b.** The remembered kernel belongs to a session for a *different* notebook. It is ignored, because only sessions on the notebook's own path are candidates.''')

code(r'''# 5a: the remembered kernel is gone
first, second = make_existing_duplicates()
RESTORATION_STATE.clear()
proposal_remember(NOTEBOOK, second)
api("DELETE", f"/api/sessions/{second['id']}")          # another client shuts the notebook's session down
model, reason = proposal_initialize(NOTEBOOK)
print("5a reload:", reason)
assert model["id"] == first["id"]

# 5b: the remembered kernel belongs to another notebook
reset_server()
other = main_start_session("other.ipynb")
own = main_start_session(NOTEBOOK)
RESTORATION_STATE[NOTEBOOK] = other["kernel"]["id"]     # a stale or wrong hint
model, reason = proposal_initialize(NOTEBOOK)
print("5b reload:", reason)
assert model["id"] == own["id"] and model["path"] == NOTEBOOK
RESULTS.append(("Proposal", "remembered kernel gone / belongs to another notebook", "-", "falls back", "-"))
print("\nBoth fallbacks connect only to a session on the notebook's own path, as main does today.")''')

md(r'''## Scenario 6. Side-effect check: changing the kernel of an existing session

PR #20426 changes the kernel of the session already on the path, and the server shuts that session's previous kernel down. Here another tab has `loop.ipynb` open normally and is running the loop in that session. A second view of the same notebook opened with "Notebook (no kernel)" then selects a kernel.

We do not claim this is a defect. **Kernel > Change Kernel** on a notebook open in two tabs has the same effect today, because both tabs share one session. It is worth stating in the pull request so maintainers can decide.''')

code(r'''reset_server()
tab1 = open_notebook_normally(NOTEBOOK)                 # tab 1: notebook open normally, loop running
start_cell(tab1["kernel"]["id"], LOOP_CELL)
print("tab 1 kernel", tab1["kernel"]["id"][:8], "is running the loop")

open_with_no_kernel(NOTEBOOK)                           # tab 2: Notebook (no kernel), then select Python 3
after_main = main_start_session(NOTEBOOK)
running_main, _ = loop_is_running()
print("main:       tab 2 got its own kernel", after_main["kernel"]["id"][:8], "| tab 1 loop", "still running" if running_main else "stopped",
      "| sessions on the path:", len(sessions_on_path()))

reset_server()
tab1 = open_notebook_normally(NOTEBOOK)
start_cell(tab1["kernel"]["id"], LOOP_CELL)
after_pr = pr20426_select_kernel(NOTEBOOK)
running_pr, _ = loop_is_running()
print("PR #20426:  session kernel changed to", after_pr["kernel"]["id"][:8], "| tab 1 loop", "still running" if running_pr else "stopped",
      "| sessions on the path:", len(sessions_on_path()))''')

md(r'''## Summary''')

code(r'''rows = ["| Behaviour | Scenario | Sessions on the path | Same kernel after reload | Restart stopped the loop |",
        "|---|---|---|---|---|"]
for behaviour, scenario, count, same, stopped in RESULTS:
    rows.append(f"| {behaviour} | {scenario} | {count} | {same} | {stopped} |")
display(Markdown("\n".join(rows)))''')

md(r'''**Reading the results.**

* **Main** reproduces the issue. A reload connects the notebook to the first session the server lists for its path, and Restart Kernel restarts that kernel.
* **PR #20426** fixes the reported steps by never creating the second session. It does not change what a reload connects to when two sessions already exist, as its description says.
* **The proposal** addresses that remaining case. A reload prefers the kernel the notebook was using, using the existing `IKernelPreference.id` field and the restoration data JupyterLab already stores, and otherwise keeps today's behaviour. It is complementary to PR #20426, not a replacement.

**Before this becomes a pull request**, the proposal needs to be implemented and tested in JupyterLab itself. That means a Jest test in `packages/apputils/test/sessioncontext.spec.ts` that fails on main, the restoration wiring in the notebook extension, and agreement from maintainers on the issue that the extra state is wanted.''')

md(r'''## Clean-up''')

code(r'''reset_server()
server.terminate()
try:
    server.wait(timeout=30)
except subprocess.TimeoutExpired:
    server.kill()
server_log.close()
print("all kernels shut down; server stopped")''')

write("session_identity_demo.ipynb", cells)
