class VocabLensError(Exception):
    """Base domain exception."""


class TranslationError(VocabLensError):
    pass


class OCRProcessingError(VocabLensError):
    pass


class PersistenceError(VocabLensError):
    pass


class NotFoundError(Exception):
    pass


class ConflictError(VocabLensError):
    pass


class ValidationError(VocabLensError):
    pass
