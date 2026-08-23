"""Lightweight additive migration runner for deployments without Alembic setup."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from database.models import create_all_tables

if __name__ == "__main__":
    create_all_tables()
