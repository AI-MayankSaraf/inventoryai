"""
Import every model module so `Base.metadata` is complete wherever this
package is imported — Alembic's `env.py` and the smoke-test/seed scripts
both rely on this.
"""

from app.models.base import Base  # noqa: F401
from app.models import identity  # noqa: F401
from app.models import master  # noqa: F401
from app.models import inventory  # noqa: F401
from app.models import procurement  # noqa: F401
from app.models import documents  # noqa: F401
from app.models import ai  # noqa: F401
from app.models import ops  # noqa: F401
from app.models import supplier_portal  # noqa: F401
