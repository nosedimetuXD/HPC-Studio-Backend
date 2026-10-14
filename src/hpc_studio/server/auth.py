"""Authentication and authorization module for HPC Studio sidecar server."""

import secrets
from typing import Optional
from fastapi import Header, HTTPException, Query, Request, WebSocket, status
from fastapi.security.utils import get_authorization_scheme_param

from hpc_studio.server.config import ServerConfig

TOKEN_HEADER = "X-HPC-Token"


def extract_token_from_request(
    request: Request,
    x_hpc_token: Optional[str] = None,
    query_x_hpc_token: Optional[str] = None,
    query_token: Optional[str] = None,
) -> Optional[str]:
    """Extract auth token from headers or query parameters."""
    if x_hpc_token:
        return x_hpc_token

    # Check X-HPC-Token header directly in case case-sensitivity varies
    header_val = request.headers.get("x-hpc-token") or request.headers.get("X-HPC-Token")
    if header_val:
        return header_val

    # Check Authorization: Bearer <token>
    auth_header = request.headers.get("Authorization")
    if auth_header:
        scheme, param = get_authorization_scheme_param(auth_header)
        if scheme.lower() == "bearer" and param:
            return param

    # Check query params
    if query_x_hpc_token:
        return query_x_hpc_token
    if query_token:
        return query_token

    return None


class TokenVerifier:
    """Dependency for validating requests against expected ephemeral token."""

    def __init__(self, config: ServerConfig):
        self.config = config

    async def __call__(
        self,
        request: Request,
        x_hpc_token: Optional[str] = Header(None, alias="X-HPC-Token"),
        query_x_hpc_token: Optional[str] = Query(None, alias="X-HPC-Token"),
        query_token: Optional[str] = Query(None, alias="token"),
    ) -> str:
        token = extract_token_from_request(
            request=request,
            x_hpc_token=x_hpc_token,
            query_x_hpc_token=query_x_hpc_token,
            query_token=query_token,
        )

        if not token or not secrets.compare_digest(token, self.config.token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized: Invalid or missing X-HPC-Token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return token


def verify_ws_token(websocket: WebSocket, expected_token: str) -> bool:
    """Validate token for incoming WebSocket connection."""
    # Check query parameters first (most common for browser WebSockets)
    token = (
        websocket.query_params.get("X-HPC-Token")
        or websocket.query_params.get("token")
        or websocket.query_params.get("x-hpc-token")
    )

    # Fallback to headers
    if not token:
        token = (
            websocket.headers.get("x-hpc-token")
            or websocket.headers.get("X-HPC-Token")
        )

    if not token:
        auth_header = websocket.headers.get("authorization") or websocket.headers.get("Authorization")
        if auth_header:
            scheme, param = get_authorization_scheme_param(auth_header)
            if scheme.lower() == "bearer" and param:
                token = param

    if not token:
        return False

    return secrets.compare_digest(token, expected_token)
