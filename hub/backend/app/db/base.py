from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def import_models() -> None:
    from app.modules.audit import models as _audit_models  # noqa: F401
    from app.modules.organizations import models as _organization_models  # noqa: F401
    from app.modules.registry import models as _registry_models  # noqa: F401
    from app.modules.submissions import models as _submission_models  # noqa: F401
    from app.modules.users import models as _users_models  # noqa: F401
