import os
import shutil
import tempfile
import pytest
import pymupdf
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


# ── Document Test Fixtures ─────────────────────────────────────────────────

@pytest.fixture(scope="session")
def sample_pdf_bytes():
    """Generate a minimal valid 1-page PDF as bytes using PyMuPDF.

    Created once per test session (cheap and deterministic).
    """
    doc = pymupdf.open()  # new empty PDF
    page = doc.new_page(width=612, height=792)  # standard US Letter
    page.insert_text((72, 72), "Test document for research platform.")
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


@pytest.fixture(scope="function")
def sample_pdf(sample_pdf_bytes):
    """Return a tuple of (filename, file-like bytes, content_type) for upload."""
    import io
    return ("test_paper.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")


@pytest.fixture(scope="function")
def sample_txt():
    """Return a non-PDF file tuple for testing file type rejection."""
    import io
    content = b"This is a plain text file, not a PDF."
    return ("notes.txt", io.BytesIO(content), "text/plain")


@pytest.fixture(scope="function")
def test_upload_dir(tmp_path):
    """Override settings.upload_dir to a temporary directory for each test.

    Automatically cleaned up after the test.
    """
    original_upload_dir = settings.upload_dir
    settings.upload_dir = str(tmp_path / "uploads")
    yield settings.upload_dir
    settings.upload_dir = original_upload_dir
