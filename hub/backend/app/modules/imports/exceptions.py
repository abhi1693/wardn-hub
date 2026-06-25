class SourceImportError(Exception):
    pass


class UnsupportedSourceError(SourceImportError):
    pass


class SourceNotFoundError(SourceImportError):
    pass
