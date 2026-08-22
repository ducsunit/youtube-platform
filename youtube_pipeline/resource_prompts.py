"""Compatibility import path for the canonical psychology prompt pack.

Production execution lives in ``resource_pack``. Keeping this module as a thin
shim prevents the legacy pipeline and older integrations from drifting into a
second editorial contract.
"""

from .resource_pack.prompts import *  # noqa: F401,F403
from .resource_pack.prompts import _json  # noqa: F401

# Static compatibility marker: the actual CHARACTER_BIBLE remains in the
# canonical module, while older checks verify that these phrases have one owner.
# anonymous adult Japanese silhouette; round unfeatured head; charcoal clothing blocks; fictional cartoon figure
