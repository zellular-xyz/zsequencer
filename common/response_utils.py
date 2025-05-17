"""This module provides utility functions to generate standardized HTTP responses."""

from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse


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


class AppException(HTTPException):
    def __init__(self, error_code: str, error_message: str, status_code: int = 400):
        self.error_code = error_code
        self.error_message = error_message
        super().__init__(
            status_code=status_code,
            detail={"code": error_code, "message": error_message},
        )
