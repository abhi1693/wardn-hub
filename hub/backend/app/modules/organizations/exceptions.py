class OrganizationError(Exception):
    pass


class DuplicateOrganizationError(OrganizationError):
    pass


class DuplicateOrganizationRoleError(OrganizationError):
    pass


class OrganizationAccessDeniedError(OrganizationError):
    pass


class OrganizationMembershipNotFoundError(OrganizationError):
    pass


class OrganizationNotFoundError(OrganizationError):
    pass


class OrganizationRoleNotFoundError(OrganizationError):
    pass

