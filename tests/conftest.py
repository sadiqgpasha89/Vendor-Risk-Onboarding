import os

# Set test environment variables prior to importing application modules
os.environ.setdefault("OPENAI_API_KEY", "mock-test-key-12345")
os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("OPENTELEMETRY_ENABLED", "false")

import pytest
import asyncio
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from src.config.settings import settings
from src.db.models import Base
from tests.fixtures.sample_data import TestDataFactory

# Create test database
TEST_DATABASE_URL = "sqlite:///./test.db"

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
)

TestingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="function")
def db() -> Generator[Session, None, None]:
    """Get test database session."""
    Base.metadata.create_all(bind=engine)

    db_session = TestingSessionLocal()
    try:
        yield db_session
    finally:
        db_session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def test_data_factory():
    """Provide test data factory."""
    return TestDataFactory


@pytest.fixture(scope="function")
def mock_settings():
    """Provide mock settings."""
    return settings


# Pytest plugins and configuration
def pytest_configure(config):
    """Configure pytest."""
    # Register custom markers
    config.addinivalue_line(
        "markers", "unit: mark test as unit test"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as integration test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow"
    )
    config.addinivalue_line(
        "markers", "llmops: mark test as llmops test"
    )
