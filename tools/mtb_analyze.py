#!/usr/bin/env python3
"""
MTB Dynamics analyser for Karoo (and Garmin) rides: entry point.

The code lives in the mtbdyn package next to this file; this module re-exports all of it, so
`import mtb_analyze` keeps working. See mtbdyn/__init__.py or --help for the inputs and options.

  python3 tools/mtb_analyze.py ride.fit --html report.html --open
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mtbdyn import *  # noqa: E402,F401,F403
from mtbdyn import __all__ as _all  # noqa: E402
from mtbdyn.cli import main  # noqa: E402

globals().update({name: getattr(sys.modules["mtbdyn"], name) for name in _all})

if __name__ == "__main__":
    sys.exit(main())
