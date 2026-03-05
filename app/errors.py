from __future__ import annotations


class DomainError(Exception):
    code: str = "INTERNAL_ERROR"
    http_status: int = 500
    retryable: bool = False

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message

    def to_error_payload(self, request_id: str) -> dict:
        return {
            "ok": False,
            "request_id": request_id,
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
            },
        }


class ModelOutputError(DomainError):
    code = "MODEL_OUTPUT_INVALID"
    http_status = 502
    retryable = True


class UpstreamTimeoutError(DomainError):
    code = "UPSTREAM_TIMEOUT"
    http_status = 504
    retryable = True


class UpstreamModelError(DomainError):
    code = "UPSTREAM_MODEL_ERROR"
    http_status = 502
    retryable = True


class CollectionEmptyError(DomainError):
    code = "COLLECTION_EMPTY"
    http_status = 404
    retryable = False


class FileFilterNoMatchError(DomainError):
    code = "FILE_FILTER_NO_MATCH"
    http_status = 404
    retryable = False


class IngestAuthError(DomainError):
    code = "INGEST_AUTH_INVALID"
    http_status = 401
    retryable = False


class InvalidPDFError(DomainError):
    code = "INVALID_PDF"
    http_status = 422
    retryable = False


class PayloadValidationError(DomainError):
    code = "PAYLOAD_VALIDATION_ERROR"
    http_status = 400
    retryable = False


class UploadTooLargeError(DomainError):
    code = "UPLOAD_TOO_LARGE"
    http_status = 413
    retryable = False
