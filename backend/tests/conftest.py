"""
pytest configuration — adds the backend/ directory to sys.path so all
test files can `import config`, `import models`, etc. without installing
the project as a package.

Run tests from the project root:
    pytest backend/tests/
"""

import sys
from pathlib import Path

# backend/ → the directory that contains auth.py, config.py, etc.
sys.path.insert(0, str(Path(__file__).parent.parent))
