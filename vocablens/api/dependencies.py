"""Legacy dependency barrel.

Prefer importing from context-scoped modules:
- vocablens.api.dependencies_auth
- vocablens.api.dependencies_admin
- vocablens.api.dependencies_interaction_api
- vocablens.api.dependencies_core / dependencies_interaction / dependencies_product

This module remains as a compatibility shim for older imports.
"""

from vocablens.api.dependencies_core import *  # noqa: F401,F403
from vocablens.api.dependencies_interaction import *  # noqa: F401,F403
from vocablens.api.dependencies_product import *  # noqa: F401,F403
