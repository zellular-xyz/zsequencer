"""This module provides utility functions to generate standardized HTTP responses."""

from typing import Any

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
