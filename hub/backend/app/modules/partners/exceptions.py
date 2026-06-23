class PartnerError(Exception):
    pass


class DuplicatePartnerSupportError(PartnerError):
    pass


class InvalidPartnerSupportError(PartnerError):
    pass


class PartnerOrganizationNotFoundError(PartnerError):
    pass


class PartnerSupportNotFoundError(PartnerError):
    pass
