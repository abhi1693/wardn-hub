class RegistryError(Exception):
    pass


class DuplicateRegistryVersionError(RegistryError):
    pass


class InvalidRegistryCursorError(RegistryError):
    pass


class RegistryServerNotFoundError(RegistryError):
    pass


class RegistryVersionNotFoundError(RegistryError):
    pass

