"""This module defines standardized error codes and messages for use across the application."""


class HttpErrorCodes:
    """HTTP error codes to be used for HTTP responses."""

    INVALID_REQUEST: int = 400
    IS_SEQUENCER: int = 403
    IS_NOT_SEQUENCER: int = 403
    INVALID_SEQUENCER: int = 400
    ISSUE_NOT_FOUND: int = 404
    PK_ALREADY_SET: int = 403
    SEQUENCER_CHANGE_NOT_APPROVED: int = 403
    PERMISSION_DENIED: int = 403
    NOT_FOUND: int = 404


class ErrorCodes:
    """Application-specific error codes as strings."""

    INVALID_REQUEST: str = "invalid_request"
    INVALID_NODE_VERSION: str = "invalid_node_version"
    NOT_SYNCED: str = "not_synced"
    IS_SEQUENCER: str = "is_sequencer"
    IS_PAUSED: str = "is_paused"
    IS_NOT_SEQUENCER: str = "is_not_sequencer"
    IS_NOT_POSTING_NODE: str = "is_not_posting_node"
    INVALID_SEQUENCER: str = "invalid_sequencer"
    ISSUE_NOT_FOUND: str = "issue_not_found"
    BATCHES_LIMIT_EXCEEDED: str = "batches_limit_exceeded"
    BATCH_SIZE_EXCEEDED: str = "batch_size_exceeded"
    PK_ALREADY_SET: str = "public_shares_already_set"
    SEQUENCER_CHANGE_NOT_APPROVED: str = "sequencer_change_not_approved"
    SEQUENCER_OUT_OF_REACH: str = "sequencer_out_of_reach"
    PERMISSION_DENIED: str = "permission_denied"
    NOT_FOUND: str = "not_found"


class ErrorMessages:
    """Human-readable error messages corresponding to error codes."""

    INVALID_REQUEST: str = "The request is invalid."
    INVALID_NODE_VERSION: str = (
        "Invalid node version. Please get the latest version of node."
    )
    NOT_SYNCED: str = "The node is not synced with the sequencer."
    IS_SEQUENCER: str = "This node is the sequencer."
    IS_PAUSED: str = "This node is paused."
    IS_NOT_SEQUENCER: str = "This node is not the sequencer."
    IS_NOT_POSTING_NODE: str = "This node does not have posting role."
    INVALID_SEQUENCER: str = "The sequencer ID is invalid."
    ISSUE_NOT_FOUND: str = "The specified issue was not found."
    BATCHES_LIMIT_EXCEEDED: str = "Batches limit volume exceeded."
    BATCH_SIZE_EXCEEDED: str = "The batch exceeds the maximum allowed size."
    PK_ALREADY_SET: str = "The public shares have already been set."
    SEQUENCER_CHANGE_NOT_APPROVED: str = "The sequencer change request is not approved."
    SEQUENCER_OUT_OF_REACH: str = "The sequencer is out of reach."
    PERMISSION_DENIED: str = "Permission denied."
    NOT_FOUND: str = "Not found."
