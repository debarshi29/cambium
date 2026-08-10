"""Import this first from any script in scripts/ so `import cambium` works
without installing the package (no setup.py/pyproject build step needed for
this project — see README for why: it's a research repo, not a library)."""
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
