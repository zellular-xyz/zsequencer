"""This module defines standardized error codes and messages for use across the application."""

from fastapi import HTTPException, status

from common.logger import zlogger


class LoggingMixin:
    def log(self):
        zlogger.error(
            f"Error occurred: Code: {self.__class__.__name__}, Status: {self.status_code}, Message: {self.message}"
        )


class BaseHTTPException(LoggingMixin, HTTPException):
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    message = "An error occurred"

    def __init__(self, message: str = None):
        super().__init__(
            status_code=self.status_code,
            detail={
                "code": self.__class__.__name__,
                "message": message or self.message,
            },
        )
        self.log()


class InvalidRequest(BaseHTTPException):
    status_code = status.HTTP_400_BAD_REQUEST
    message = "The request is invalid."


class IsSequencer(BaseHTTPException):
    status_code = status.HTTP_403_FORBIDDEN
    message = (
        "This node is the sequencer and this route is not available on the sequencer."
    )


class IsNotSequencer(BaseHTTPException):
    status_code = status.HTTP_403_FORBIDDEN
    message = "This node is not the sequencer and this route is only available on the sequencer."


class NotSynced(BaseHTTPException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    message = "The node is not synced with the sequencer."


class InvalidSequencer(BaseHTTPException):
    status_code = status.HTTP_400_BAD_REQUEST
    message = "The sequencer ID is invalid."


class IssueNotFound(BaseHTTPException):
    status_code = status.HTTP_404_NOT_FOUND
    message = "The specified issue was not found."


class PKAlreadySet(BaseHTTPException):
    status_code = status.HTTP_403_FORBIDDEN
    message = "The public shares have already been set."


class SequencerChangeNotApproved(BaseHTTPException):
    status_code = status.HTTP_403_FORBIDDEN
    message = "The sequencer change request is not approved."


class PermissionDenied(BaseHTTPException):
    status_code = status.HTTP_403_FORBIDDEN
    message = "Permission denied."


class NotFound(BaseHTTPException):
    status_code = status.HTTP_404_NOT_FOUND
    message = "Not found."


class SequencerOutOfReach(BaseHTTPException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    message = "The sequencer is out of reach."


class InvalidNodeVersion(BaseHTTPException):
    status_code = status.HTTP_400_BAD_REQUEST
    message = "Invalid node version. Please get the latest version of node."


class IsPaused(BaseHTTPException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    message = "This node is paused."


class IsNotPostingNode(BaseHTTPException):
    status_code = status.HTTP_403_FORBIDDEN
    message = "This node does not have posting role."


class BatchesLimitExceeded(BaseHTTPException):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    message = "Batches limit volume exceeded."


class BatchSizeExceeded(BaseHTTPException):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    message = "The batch exceeds the maximum allowed size."
