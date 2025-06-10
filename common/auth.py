import json

import aiohttp
from fastapi import Header, Request

from common import bls, utils
from common.errors import (
    InvalidRequestError,
    PermissionDeniedError,
)
from config import zconfig


class CustomClientSession(aiohttp.ClientSession):
    async def _request(self, method, url, **kwargs):
        headers = kwargs.get("headers", {})
        headers["Content-Type"] = "application/json"
        headers["Version"] = zconfig.VERSION

        if method in ("PUT", "POST") and kwargs.get("json"):
            body = json.dumps(kwargs.get("json"))

            # Hash and sign
            body_hash = utils.gen_hash(body)
            signature = bls.bls_sign(body_hash)

            # Inject signature
            headers["Signature"] = signature
            headers["Signer"] = zconfig.NODE["id"]

        kwargs["headers"] = headers
        kwargs["raise_for_status"] = True
        if "timeout" not in kwargs:
            kwargs["timeout"] = aiohttp.ClientTimeout(total=5)
        return await super()._request(method, url, **kwargs)


async def authenticate(
    request: Request, signature: str = Header(None), signer: str = Header(None)
) -> None:
    """Decorator to authenticate the request."""
    if not signature:
        raise PermissionDeniedError("Signature header is required")
    if signer is None:
        raise PermissionDeniedError("Signer header is required")
    if signer not in zconfig.NODES:
        raise PermissionDeniedError(f"{signer} is not a valid node id")

    body = await request.body()
    if not body:
        raise InvalidRequestError("Empty request body")

    body_hash = utils.gen_hash(body.decode("utf-8"))
    verified = bls.is_bls_sig_verified(
        signature, body_hash, zconfig.NODES[signer]["public_key_g2"]
    )
    if not verified:
        raise PermissionDeniedError(
            f"Signature verification failed. {signature=}, {signer=}, {body=}, headers: {dict(request.headers)}"
        )

    route_path = request.url.path
    if "/sign_sync_point" in route_path:
        if signer != zconfig.SEQUENCER["id"]:
            raise PermissionDeniedError(
                "Only the current sequencer can call this endpoint"
            )
