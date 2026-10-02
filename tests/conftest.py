import pytest
from sqlmodel import Session

from app.db import make_engine, migrate


@pytest.fixture
def engine(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    migrate(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture
def client(engine):
    """TestClient whose requests use the per-test database."""
    from fastapi.testclient import TestClient

    from app.db import get_session
    from app.main import app

    def override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = override
    yield TestClient(app)
    app.dependency_overrides.clear()
