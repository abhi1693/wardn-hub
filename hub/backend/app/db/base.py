from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def import_models() -> None:
    # Phase 0 has no persisted domain models yet. Later phases import modules here
    # so Alembic can collect metadata for autogeneration.
    return None

