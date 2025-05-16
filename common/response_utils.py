"""This module provides utility functions to generate standardized HTTP responses."""

from typing import Any

from fastapi.responses import JSONResponse

from .errors import ErrorMessages, HttpErrorCodes


def success_response(
    data: Any,
    message: str = "Operation successful",
    status: int = 200,
) -> JSONResponse:
    return JSONResponse(
        content={
            "status": "success",
            "message": message,
            "data": data,
        },
        status_code=status,
    )


def error_response(error_code: str, error_message: str = "") -> JSONResponse:
    if not error_message:
        error_message = getattr(ErrorMessages, error_code, "An unknown error occurred.")
    http_status = getattr(HttpErrorCodes, error_code, 500)
    return JSONResponse(
        content={
            "status": "error",
            "error": {
                "code": error_code,
                "message": error_message,
            },
            "data": None,
        },
        status_code=http_status,
    )
