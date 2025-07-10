import aiohttp
from fastapi import Header, Request

from common import bls, utils
from common.errors import (
    InvalidRequestError,
    PermissionDeniedError,
)
from config import zconfig


def create_session() -> aiohttp.ClientSession:
    timeout = aiohttp.ClientTimeout(total=5)
    return aiohttp.ClientSession(
        middlewares=(custom_middleware,), raise_for_status=True, timeout=timeout
    )


async def custom_middleware(
    req: aiohttp.ClientRequest, handler: aiohttp.ClientHandlerType
) -> aiohttp.ClientResponse:
    req.headers["Content-Type"] = "application/json"
    req.headers["Version"] = zconfig.VERSION

    if req.method in ("PUT", "POST") and req.body:
        body = await req.body.as_bytes()
        body_hash = utils.gen_hash(body)
        signature = bls.bls_sign(body_hash)

        req.headers["Signature"] = signature
        req.headers["Signer"] = zconfig.NODE["id"]

    response = await handler(req)
    return response


async def verify_node_access(
    request: Request,
    signature: str | None = Header(None),
    signer: str | None = Header(None),
) -> None:
    """Dependency to verify that the request is from a valid network node."""
    if signature is None:
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


async def verify_sequencer_access(
    request: Request,
    signature: str | None = Header(None),
    signer: str | None = Header(None),
) -> None:
    """Dependency to verify that the request is from the current sequencer node."""
    await verify_node_access(request, signature, signer)
    if signer != zconfig.SEQUENCER["id"]:
        raise PermissionDeniedError("Only the current sequencer can call this endpoint")
