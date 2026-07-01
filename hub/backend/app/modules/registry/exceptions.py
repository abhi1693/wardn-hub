class RegistryError(Exception):
    pass


class DuplicateRegistryVersionError(RegistryError):
    pass


class DuplicateRegistryCategoryError(RegistryError):
    pass


class InvalidRegistryVersionError(RegistryError):
    pass


class InvalidRegistryCursorError(RegistryError):
    pass


class RegistryCategoryNotFoundError(RegistryError):
    pass


class RegistryServerNotFoundError(RegistryError):
    pass


class RegistryVersionNotFoundError(RegistryError):
    pass


class RegistryAccessDeniedError(RegistryError):
    pass


class RegistryOwnershipClaimError(RegistryError):
    pass


class RegistryOwnershipClaimConflictError(RegistryError):
    pass
