class DomainError(Exception):
    """Safe error suitable for application boundaries."""


class JobValidationError(DomainError):
    pass


class JobNotFoundError(DomainError):
    pass


class UnsupportedChannelError(DomainError):
    pass


class ChannelDeliveryError(DomainError):
    pass


class OpenWebUiError(DomainError):
    pass


class PromptLoadError(DomainError):
    pass


class RepositoryError(DomainError):
    pass
