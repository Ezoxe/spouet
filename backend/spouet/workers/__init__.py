"""Celery app + tâches.

Importable comme `celery -A spouet.workers worker`.
"""

from spouet.workers.app import celery_app

__all__ = ["celery_app"]

# Convention : Celery cherche `celery_app` ou `app` dans le module
app = celery_app
