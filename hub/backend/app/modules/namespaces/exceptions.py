class NamespaceError(Exception):
    pass


class DuplicateNamespaceClaimError(NamespaceError):
    pass


class InvalidNamespaceError(NamespaceError):
    pass


class NamespaceAccessDeniedError(NamespaceError):
    pass


class NamespaceClaimNotFoundError(NamespaceError):
    pass


class InvalidNamespaceClaimTransitionError(NamespaceError):
    pass
