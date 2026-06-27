class EventRuleNotFoundError(Exception):
    pass


class EventDeliveryNotFoundError(Exception):
    pass


class EventAccessDeniedError(Exception):
    pass


class EventValidationError(Exception):
    pass


class EventDeliveryError(Exception):
    pass
