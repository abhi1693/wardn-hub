class SubmissionError(Exception):
    pass


class DuplicatePublishedVersionError(SubmissionError):
    pass


class InvalidSubmissionTransitionError(SubmissionError):
    pass


class SubmissionAccessDeniedError(SubmissionError):
    pass


class SubmissionNotFoundError(SubmissionError):
    pass


class SubmissionValidationError(SubmissionError):
    pass
