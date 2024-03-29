class HtmlErrorCodes:
    INVALID_REQUEST = 400
    IS_SEQUENCER = 403
    IS_NOT_SEQUENCER = 403
    INVALID_SEQUENCER = 400
    ISSUE_NOT_FOUND = 404
    PK_ALREADY_SET = 403
    SEQUENCER_CHANGE_NOT_APPROVED = 403
    PERMISSION_DENIED = 403


class ErrorCodes:
    INVALID_REQUEST = "invalid_request"
    IS_SEQUENCER = "is_sequencer"
    IS_NOT_SEQUENCER = "is_not_sequencer"
    INVALID_SEQUENCER = "invalid_sequencer"
    ISSUE_NOT_FOUND = "issue_not_found"
    PK_ALREADY_SET = "public_shares_already_set"
    SEQUENCER_CHANGE_NOT_APPROVED = "sequencer_change_not_approved"
    PERMISSION_DENIED = "permission_denied"


class ErrorMessages:
    INVALID_REQUEST = "The request is invalid."
    IS_SEQUENCER = "This node is sequencer."
    IS_NOT_SEQUENCER = "This node is not sequencer."
    INVALID_SEQUENCER = "The sequencer id is invalid."
    ISSUE_NOT_FOUND = "There is no issue."
    PK_ALREADY_SET = "The public shares already set."
    SEQUENCER_CHANGE_NOT_APPROVED = "The sequencer change request is not approved."
    PERMISSION_DENIED = "The request is not approved."
