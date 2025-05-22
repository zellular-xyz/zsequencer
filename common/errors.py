"""This module defines standardized error codes and messages for use across the application."""

from fastapi import HTTPException, status


class BaseHTTPError(HTTPException):
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    message = "An error occurred"

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


class IsSequencerError(BaseHTTPError):
    status_code = status.HTTP_403_FORBIDDEN
    message = (
        "This node is the sequencer and this route is not available on the sequencer."
    )


class IsNotSequencerError(BaseHTTPError):
    status_code = status.HTTP_403_FORBIDDEN
    message = "This node is not the sequencer and this route is only available on the sequencer."


class NotSyncedError(BaseHTTPError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    message = "The node is not synced with the sequencer."


class InvalidSequencerError(BaseHTTPError):
    status_code = status.HTTP_400_BAD_REQUEST
    message = "The sequencer ID is invalid."


class IssueNotFoundError(BaseHTTPError):
    status_code = status.HTTP_404_NOT_FOUND
    message = "The specified issue was not found."


class SequencerChangeNotApprovedError(BaseHTTPError):
    status_code = status.HTTP_403_FORBIDDEN
    message = "The sequencer change request is not approved."


class PermissionDeniedError(BaseHTTPError):
    status_code = status.HTTP_403_FORBIDDEN
    message = "Permission denied."


class SequencerOutOfReachError(BaseHTTPError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    message = "The sequencer is out of reach."


class InvalidNodeVersionError(BaseHTTPError):
    status_code = status.HTTP_400_BAD_REQUEST
    message = "Invalid node version. Please get the latest version of node."


class IsPausedError(BaseHTTPError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    message = "This node is paused."


class IsNotPostingNodeError(BaseHTTPError):
    status_code = status.HTTP_403_FORBIDDEN
    message = "This node does not have posting role."


class BatchesLimitExceededError(BaseHTTPError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    message = "Batches limit volume exceeded."


class BatchSizeExceededError(BaseHTTPError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    message = "The batch exceeds the maximum allowed size."
