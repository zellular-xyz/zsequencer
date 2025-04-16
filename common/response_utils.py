"""This module provides utility functions to generate standardized HTTP responses."""

from typing import Any

from flask import Response, jsonify, make_response

from .errors import ErrorMessages, HttpErrorCodes


def success_response(
    data: Any,
    message: str = "Operation successful",
    status: int = 200,
) -> Response:
    """Generate a successful HTTP response."""
    return make_response(
        jsonify(
            {
                "status": "success",
                "message": message,
                "data": data,
            },
        ),
        status,
    )


def error_response(error_code: str, error_message: str = "") -> Response:
    """Generate an error HTTP response."""
    if not error_message:
        error_message = getattr(ErrorMessages, error_code, "An unknown error occurred.")
    http_status = getattr(HttpErrorCodes, error_code, 500)
    return make_response(
        jsonify(
            {
                "status": "error",
                "error": {
                    "code": error_code,
                    "message": error_message,
                },
                "data": None,
            },
        ),
        http_status,
    )
