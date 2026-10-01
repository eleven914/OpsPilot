import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine

TEST_DATABASE_PATH = Path(__file__).resolve().parents[1] / "test-opspilot.db"
os.environ["OPSPILOT_DATABASE_URL"] = (
    f"sqlite+aiosqlite:///{TEST_DATABASE_PATH.as_posix()}"
)

from opspilot.models import Base  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def prepare_test_database() -> Iterator[None]:
    sync_engine = create_engine(f"sqlite:///{TEST_DATABASE_PATH.as_posix()}")
    Base.metadata.drop_all(sync_engine)
    Base.metadata.create_all(sync_engine)

    yield

    Base.metadata.drop_all(sync_engine)
    sync_engine.dispose()
    TEST_DATABASE_PATH.unlink(missing_ok=True)
