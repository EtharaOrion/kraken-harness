"""Conftest: pre-register swefficiency as a namespace to bypass heavy __init__.py imports.

Also disables the persistent version cache so HTTP-mock based tests are not
short-circuited by entries from earlier real-network runs.
"""

import os
import sys
import types

# Disable the SQLite version cache for the entire versioning test suite.
# Production callers can still opt in via the same env var.
os.environ.setdefault("SWEFF_DISABLE_CACHE", "1")

# Only do this if swefficiency hasn't been imported yet
if "swefficiency" not in sys.modules:
    _pkg = types.ModuleType("swefficiency")
    _pkg.__path__ = ["swefficiency"]
    _pkg.__package__ = "swefficiency"
    sys.modules["swefficiency"] = _pkg

    _versioning = types.ModuleType("swefficiency.versioning")
    _versioning.__path__ = ["swefficiency/versioning"]
    _versioning.__package__ = "swefficiency.versioning"
    sys.modules["swefficiency.versioning"] = _versioning

    # Wire subpackage attribute so mock.patch() can traverse dotted paths
    _pkg.versioning = _versioning
