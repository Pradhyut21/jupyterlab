# Demo: a page reload can connect a notebook to another kernel (jupyterlab#20372)

Issue: https://github.com/jupyterlab/jupyterlab/issues/20372
Related pull request by another contributor: https://github.com/jupyterlab/jupyterlab/pull/20426

## What is in this folder

| File | Purpose |
|---|---|
| `session_identity_demo.ipynb` | The demo. It reproduces the bug, runs the approach of PR #20426, and runs our proposal, against a real Jupyter Server. It already contains the outputs of a real run, and can be re-run live. |
| `loop.ipynb` | The two-cell notebook from the issue, for reproducing the bug by hand in the browser. The loop stops by itself after 10 minutes. |
| `tools/build_notebooks.py` | Regenerates both notebooks from readable source. |
| `tools/show_outputs.py` | Prints the recorded outputs of the demo notebook in a terminal. |

## The problem in one paragraph

When the server has two sessions for one notebook, reloading the page connects the notebook to the first session the server lists for its path. That is the older session, not the one the notebook was using. Restart Kernel then restarts the wrong kernel, and the code the notebook started keeps running. Since JupyterLab 4.6.0, "Open With > Notebook (no kernel)" followed by selecting a kernel creates that second session.

## What the demo shows

Results from our run on Windows 11, Python 3.13.5, Jupyter Server 2.21.1, JupyterLab 4.6.5 packages. The team's full write-up is in [`README-MACHZERO.md`](../../README-MACHZERO.md) at the root of the fork.

| Behaviour | Scenario | Sessions on the path | Same kernel after reload | Restart stopped the loop |
|---|---|---|---|---|
| Main (4.6.x) | the issue's steps | 2 | no | no (bug) |
| PR #20426 | the issue's steps | 1 | yes | yes |
| PR #20426 | two sessions already exist | 2 | no | no |
| Our proposal | two sessions already exist | 2 | yes | yes |
| Our proposal | remembered kernel gone, or belongs to another notebook | - | falls back to today's choice | - |

* **PR #20426** stops new duplicate sessions from being created. That fixes the reported steps. Its description states that a notebook which already has two sessions is not fixed.
* **Our proposal** makes a reloaded notebook reconnect to the kernel it was using. JupyterLab already stores restoration data for every open notebook, and `ISessionContext.IKernelPreference` already has an `id` field ("The id of an existing kernel"). On reload, the notebook prefers the session on its own path that has that kernel. If that kernel is gone, it falls back to today's behaviour. This covers the case PR #20426 leaves open, and it is complementary to that PR, not a replacement.
* **Side-effect check (scenario 6):** changing the kernel of the existing session, as PR #20426 does, stops code that another tab is running in that session. Kernel > Change Kernel has the same effect today, so we do not call it a defect, but it is worth stating to maintainers.

### What is real and what is modelled

The Jupyter Server, sessions, kernels, kernel processes and the looping cell are real. The JupyterLab front-end is not running. Each front-end step is a Python transcription of the TypeScript in `packages/apputils/src/sessioncontext.tsx` (commit `29752fe`, linked in the notebook), and it sends the same REST requests. **Our proposal is a design demonstrated with this model; it is not implemented in JupyterLab yet.**

## Run the demo

You need Python 3.10 or newer. Run these from this folder (`machzero/jupyterlab-20372-demo` in the team fork).

**Windows (PowerShell)**

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install "jupyterlab==4.6.5" nbconvert nbformat requests
$env:PYTHONNOUSERSITE = '1'
.venv\Scripts\python.exe -m jupyterlab
```

**macOS / Linux**

```bash
python3 -m venv .venv
.venv/bin/python -m pip install "jupyterlab==4.6.5" nbconvert nbformat requests
PYTHONNOUSERSITE=1 .venv/bin/python -m jupyterlab
```

In JupyterLab, open `session_identity_demo.ipynb`, check that the kernel at the top right is **Python 3 (ipykernel)**, and click **Run → Run All Cells**. It takes about 80 seconds.

Start JupyterLab with `python -m jupyterlab` from the venv, as shown. A plain `jupyter lab` command can pick up a different Jupyter installed elsewhere on the machine. Do not open files inside `demo-run/`: the demo recreates that folder each time it runs.

To re-run headlessly and refresh the saved outputs:

```powershell
$env:PYTHONNOUSERSITE = '1'
.venv\Scripts\python.exe -m nbconvert --to notebook --execute --inplace session_identity_demo.ipynb --ExecutePreprocessor.timeout=900
.venv\Scripts\python.exe tools\show_outputs.py
```

The demo starts its own Jupyter Server on a random free port, under `demo-run/`. Its last cell shuts down every kernel and the server.

## Manual browser reproduction (the issue's steps, JupyterLab 4.6.5)

1. Start JupyterLab from the venv as above, in this folder. If you need to be on JupyterLab 4.6.5 exactly, keep the pinned version.
2. Open `loop.ipynb`, wait until the kernel status shows Idle, and close the notebook tab. The kernel keeps running.
3. In the file browser, right-click `loop.ipynb` and select Open With > Notebook (no kernel).
4. Click "No Kernel" in the toolbar, keep "Python 3 (ipykernel)", and click Select.
5. Run the first cell.
6. Reload the page.
7. Restart the kernel from the toolbar, and confirm.
8. Run the second cell. If the second `loop:` timestamp is later than the first, the loop is still running in another kernel: the bug.

The running sessions count in the status bar shows 2.

## Before this becomes a pull request

1. Implement the proposal in a JupyterLab checkout. That means the session selection in `SessionContext._initialize` plus the restoration wiring in the notebook extension. Add a Jest test in `packages/apputils/test/sessioncontext.spec.ts` that fails on main.
2. Check in on the issue first. Comments must be in your own words, and JupyterLab's pull request template requires disclosing AI use, including tools, models and effort level.
3. Reference PR #20426 and explain that this change covers the case it leaves open.
