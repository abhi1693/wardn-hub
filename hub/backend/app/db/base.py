from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def import_models() -> None:
    from app.modules.organizations import models as _organization_models  # noqa: F401
    from app.modules.registry import models as _registry_models  # noqa: F401
    from app.modules.users import models as _users_models  # noqa: F401
