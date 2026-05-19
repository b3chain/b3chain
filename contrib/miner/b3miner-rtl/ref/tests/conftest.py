"""pytest config: prepend `ref/` to sys.path so `import b3pow_ref` works."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
