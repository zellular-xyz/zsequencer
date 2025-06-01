"""This module defines standardized error codes and messages for use across the application."""

import logging

from fastapi import HTTPException, status


class BaseHTTPError(HTTPException):
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    message = "An error occurred"
    log_level = logging.ERROR

    def __init__(self, message: str = None):
        super().__init__(
            status_code=self.status_code,
            detail={
                "status": "error",
                "error": {
                    "code": self.__class__.__name__,
                    "message": message or self.message,
                },
            },
        )


class InvalidRequestError(BaseHTTPError):
    status_code = status.HTTP_400_BAD_REQUEST
    message = "The request is invalid."
    log_level = logging.ERROR


class IsSequencerError(BaseHTTPError):
    status_code = status.HTTP_403_FORBIDDEN
    message = (
        "This node is the sequencer and this route is not available on the sequencer."
    )
    log_level = logging.DEBUG


class IsNotSequencerError(BaseHTTPError):
    status_code = status.HTTP_403_FORBIDDEN
    message = "This node is not the sequencer and this route is only available on the sequencer."
    log_level = logging.DEBUG


class NotSyncedError(BaseHTTPError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    message = "The node is not synced with the sequencer."
    log_level = logging.WARNING


class InvalidSequencerError(BaseHTTPError):
    status_code = status.HTTP_400_BAD_REQUEST
    message = "The sequencer ID is invalid."
    log_level = logging.INFO


class IssueNotFoundError(BaseHTTPError):
    status_code = status.HTTP_404_NOT_FOUND
    message = "The specified issue was not found."
    log_level = logging.INFO


class SequencerChangeNotApprovedError(BaseHTTPError):
    status_code = status.HTTP_403_FORBIDDEN
    message = "The sequencer change request is not approved."
    log_level = logging.INFO


class PermissionDeniedError(BaseHTTPError):
    status_code = status.HTTP_403_FORBIDDEN
    message = "Permission denied."
    log_level = logging.ERROR


class InvalidNodeVersionError(BaseHTTPError):
    status_code = status.HTTP_400_BAD_REQUEST
    message = "Invalid node version. Please get the latest version of node."
    log_level = logging.DEBUG


class IsPausedError(BaseHTTPError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    message = "This node is paused."
    log_level = logging.DEBUG


class IsNotPostingNodeError(BaseHTTPError):
    status_code = status.HTTP_403_FORBIDDEN
    message = "This node does not have posting role."
    log_level = logging.DEBUG


class BatchesLimitExceededError(BaseHTTPError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    message = "Batches limit volume exceeded."
    log_level = logging.ERROR


class BatchSizeExceededError(BaseHTTPError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    message = "The batch exceeds the maximum allowed size."
    log_level = logging.WARNING
