from sqlalchemy import text


def test_database_session(db_session):
    """
    Test that the database session works and can execute a basic query.
    """
    result = db_session.execute(text("SELECT 1"))
    assert result.scalar() == 1
