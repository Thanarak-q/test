"""ORM models. Alembic autogenerate imports this module, so every table must land here.

Table names carry a domain prefix (money_transactions, task_items) and every
user-owned table carries user_id, even while the app has a single user.
"""

from app.db import Base

__all__ = ["Base"]
