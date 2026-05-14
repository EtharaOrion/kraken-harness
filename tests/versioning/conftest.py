"""Conftest: pre-register swefficiency as a namespace to bypass heavy __init__.py imports."""

import sys
import types

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
