"""Print the recorded outputs of an executed notebook (default: session_identity_demo.ipynb)."""
import sys

import nbformat

path = sys.argv[1] if len(sys.argv) > 1 else "session_identity_demo.ipynb"
nb = nbformat.read(path, as_version=4)
for index, cell in enumerate(nb.cells):
    if cell.cell_type != "code":
        continue
    print(f"--- cell {index}")
    for output in cell.get("outputs", []):
        data = output.get("data", {})
        print(output.get("text") or data.get("text/markdown") or data.get("text/plain") or output)
