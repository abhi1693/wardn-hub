class UserError(Exception):
    pass


class BootstrapUserExistsError(UserError):
    pass


class DuplicateUserError(UserError):
    pass


class InvalidAPITokenScopeError(UserError):
    pass


class InvalidLoginError(UserError):
    pass


class UserAPITokenNotFoundError(UserError):
    pass


class UserNotFoundError(UserError):
    pass

