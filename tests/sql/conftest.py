"""
Minimal pytest fixtures for SQL testing.
"""
import os
import pytest
import json
from pathlib import Path
from sqlalchemy import create_engine, text, exc


# The repository-wide conftest disables database initialization for unit tests.
# SQL tests explicitly opt back in and direct Flask to the disposable test DB
# before any test module imports ``app``.
_config_path = Path(__file__).parent / "database_test.json"
with open(_config_path) as _config_file:
    _bootstrap_config = json.load(_config_file)
os.environ["BUCKAROO_SKIP_DB_INIT"] = "0"
os.environ["BUCKAROO_DB_HOST"] = str(_bootstrap_config["host"])
os.environ["BUCKAROO_DB_PORT"] = str(_bootstrap_config["port"])
os.environ["BUCKAROO_DB_USER"] = str(_bootstrap_config["user"])
os.environ["BUCKAROO_DB_PASSWORD"] = str(_bootstrap_config["password"])
os.environ["BUCKAROO_DB_NAME"] = str(_bootstrap_config["db_name"])


def _get_db_url(config, db_name=None):
    """Build database URL from config"""
    db = db_name or config["db_name"]
    return f"postgresql+psycopg2://{config['user']}:{config['password']}@{config['host']}:{config['port']}/{db}"


@pytest.fixture(scope="session")
def test_db_config():
    """Load test database configuration.

    Values from database_test.json can be overridden with environment
    variables so the suite can target a Dockerized Postgres without editing
    the committed config (e.g. BUCKAROO_TEST_DB_PASSWORD=password).
    """
    config_path = Path(__file__).parent / "database_test.json"
    with open(config_path) as f:
        config = json.load(f)

    env_overrides = {
        "host": os.environ.get("BUCKAROO_TEST_DB_HOST"),
        "port": os.environ.get("BUCKAROO_TEST_DB_PORT"),
        "user": os.environ.get("BUCKAROO_TEST_DB_USER"),
        "password": os.environ.get("BUCKAROO_TEST_DB_PASSWORD"),
        "db_name": os.environ.get("BUCKAROO_TEST_DB_NAME"),
    }
    config.update({key: value for key, value in env_overrides.items() if value})
    return config


@pytest.fixture(scope="session")
def _admin_engine(test_db_config):
    """Admin engine for database management (internal fixture)"""
    engine = create_engine(
        _get_db_url(test_db_config, "postgres"),
        isolation_level="AUTOCOMMIT"
    )
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def test_database(_admin_engine, test_db_config):
    """Create and drop test database"""
    db_name = test_db_config["db_name"]

    # Create database if needed
    with _admin_engine.connect() as conn:
        result = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": db_name}
        )
        if not result.scalar():
            # Can't use parameters for CREATE DATABASE
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))

    yield db_name

    # Cleanup: terminate connections and drop database
    with _admin_engine.connect() as conn:
        try:
            conn.execute(text("""
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = :name AND pid <> pg_backend_pid()
            """), {"name": db_name})
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
        except exc.SQLAlchemyError as e:
            # Log but don't fail - cleanup is best-effort
            print(f"Warning: Failed to cleanup test database: {e}")


@pytest.fixture(scope="session")
def test_engine(test_database, test_db_config):
    """SQLAlchemy engine for test database"""
    engine = create_engine(_get_db_url(test_db_config))
    yield engine
    engine.dispose()


@pytest.fixture
def db_connection(test_engine):
    """
    Connection with NO automatic rollback.

    Use when you need to test:
    - Commit/rollback logic
    - Database triggers
    - Cross-transaction behavior

    Note: Changes persist, so clean up manually or use unique table names.
    """
    conn = test_engine.connect()
    yield conn
    conn.close()


@pytest.fixture
def db_transaction(test_engine):
    """
    Connection with automatic rollback for isolated unit tests.

    Use this fixture (recommended default) when you want:
    - Fast, isolated tests
    - Automatic cleanup
    - No test interference

    Changes are never committed - everything rolls back after the test.
    Perfect for testing business logic without worrying about cleanup.
    """
    conn = test_engine.connect()
    trans = conn.begin()
    yield conn
    trans.rollback()
    conn.close()
