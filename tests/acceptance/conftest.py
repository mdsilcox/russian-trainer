"""Fixtures for the acceptance suites; the shared code lives in acc_common.py (a unique module name,
since several folders here have their own conftest.py)."""

from acc_common import *  # noqa: F401,F403
from acc_common import _no_real_claude  # noqa: F401  (autouse; star imports skip underscored names)
