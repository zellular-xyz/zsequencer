from typing import Any

from flask import Response, jsonify, make_response

from .errors import ErrorMessages, HtmlErrorCodes


def success_response(
    data: Any, message: str = "Operation successful", status: int = 200
) -> Response:
    return make_response(
        jsonify(
            {
                "status": "success",
                "message": message,
                "data": data,
            }
        ),
        status,
    )


def error_response(error_code: str, error_message: str = "") -> Response:
    if not error_message:
        error_message = getattr(ErrorMessages, error_code, "An unknown error occurred.")
    http_status = getattr(HtmlErrorCodes, error_code, 500)
    return make_response(
        jsonify(
            {
                "status": "error",
                "error": {
                    "code": error_code,
                    "message": error_message,
                },
                "data": None,
            }
        ),
        http_status,
    )
