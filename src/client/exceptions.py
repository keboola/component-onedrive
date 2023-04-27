class BaseError(Exception):
    """
    Example:
        error_obj = {
            "error": {
                "code": "invalidRequest",
                "message": "Invalid hostname for this tenancy",
                "innerError": {
                    "request-id": "80fc571a-3262-404b-8a67-22f9cad99016",
                    "date": "2020-01-14T19:01:55"
                }
            }
        }
    """

    def __init__(self, msg, error_obj):
        if isinstance(error_obj.get("error", {}), str):
            Exception.__init__(self, msg + f' Error: {error_obj.get("error", {})}')
            self.error_obj = {}
        else:
            Exception.__init__(self, msg + f' Error: {error_obj.get("error", {}).get("message")}'
                                           f', error code: {error_obj.get("error", {}).get("code")}')
        self.error_obj = error_obj


class UnknownError(BaseError):
    pass


class TokenRequired(BaseError):
    pass


class BadRequest(BaseError):
    pass


class Unauthorized(BaseError):
    pass


class Forbidden(BaseError):
    pass


class NotFound(BaseError):
    pass


class MethodNotAllowed(BaseError):
    pass


class NotAcceptable(BaseError):
    pass


class Conflict(BaseError):
    pass


class Gone(BaseError):
    pass


class LengthRequired(BaseError):
    pass


class PreconditionFailed(BaseError):
    pass


class RequestEntityTooLarge(BaseError):
    pass


class UnsupportedMediaType(BaseError):
    pass


class RequestedRangeNotSatisfiable(BaseError):
    pass


class UnprocessableEntity(BaseError):
    pass


class TooManyRequests(BaseError):
    pass


class InternalServerError(BaseError):
    pass


class NotImplemented(BaseError):
    pass


class ServiceUnavailable(BaseError):
    pass


class GatewayTimeout(BaseError):
    pass


class InsufficientStorage(BaseError):
    pass


class BandwidthLimitExceeded(BaseError):
    pass
