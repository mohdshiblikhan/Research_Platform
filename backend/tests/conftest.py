import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

# We set the test database URL explicitly before importing settings/app
TEST_DATABASE_URL = "postgresql+psycopg://mohdshiblikhan@localhost:5432/research_platform_test"
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from app.main import app
from app.db.session import get_db, SessionLocal, engine
from app.db.base_class import Base
from app.core.config import settings

# Override the engine and SessionLocal to point to our test database
# just in case `app.db.session` already initialized them with the dev DB URL.
test_engine = create_engine(TEST_DATABASE_URL)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Create all tables in the test database before tests run."""
    # Note: The test database `research_platform_test` must already exist.
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)

@pytest.fixture(scope="function")
def db_session():
    """Provides a transactional database session for each test."""
    connection = test_engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)
    
    yield session
    
    session.close()
    transaction.rollback()
    connection.close()

@pytest.fixture(scope="function")
def client(db_session):
    """Provides a FastAPI TestClient that overrides the get_db dependency."""
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
