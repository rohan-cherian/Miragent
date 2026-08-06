"""
OAuth2 utilities for production connectors.

Handles token acquisition, refresh, and caching. Supports Authorization Code
flow (for user-context APIs like Salesforce) and Client Credentials flow (for
server-to-server APIs like HubSpot Private Apps).

Thread safety: OAuth2ClientCredentials uses a threading.Lock to prevent
multiple threads from refreshing the same token simultaneously (thundering herd
problem). OAuth2AuthorizationCode is stateless — callers are responsible for
persisting and passing the OAuth2Token between calls.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urlencode, urljoin

import httpx

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# TOKEN DATACLASS
# ─────────────────────────────────────────────────────────

@dataclass
class OAuth2Token:
    """
    Represents an OAuth2 access token with optional refresh token.

    expires_at is a Unix timestamp (float). The is_expired() method
    adds a 60-second buffer so we refresh slightly before actual expiry,
    preventing in-flight requests from hitting a 401.
    """
    access_token: str
    refresh_token: str | None = None
    expires_at: float = 0.0          # Unix timestamp; 0.0 means unknown/never set
    token_type: str = "Bearer"

    def is_expired(self) -> bool:
        """
        Return True if the token has expired or is about to expire.

        The 60-second buffer ensures we refresh before the token actually
        becomes invalid, avoiding 401s on in-flight requests.

        If expires_at == 0.0 (never set), we treat the token as expired so
        callers always refresh on the first use.
        """
        if self.expires_at == 0.0:
            return True
        return time.time() >= self.expires_at - 60


# ─────────────────────────────────────────────────────────
# CLIENT CREDENTIALS GRANT
# ─────────────────────────────────────────────────────────

class OAuth2ClientCredentials:
    """
    Client credentials grant (server-to-server). Used by HubSpot Private Apps,
    Workday ISU integrations, and any service-to-service OAuth2 flow.

    This grant type does not involve a user — the application authenticates
    as itself using its client_id and client_secret. Suitable for background
    jobs and automated pipelines.

    Thread safety: get_valid_token() uses a Lock so that multiple threads
    sharing one instance don't simultaneously trigger a refresh storm.
    """

    def __init__(
        self,
        token_url: str,
        client_id: str,
        client_secret: str,
        scope: str = "",
    ) -> None:
        self._token_url = token_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._scope = scope
        self._cached_token: OAuth2Token | None = None
        self._lock = threading.Lock()

    def get_token(self) -> OAuth2Token:
        """
        POST to token_url with grant_type=client_credentials.

        Returns a fresh OAuth2Token. Does NOT cache — callers should use
        get_valid_token() for cached access.

        Raises:
            httpx.HTTPStatusError if the token endpoint returns an error.
            httpx.RequestError on network failures.
        """
        form_data: dict[str, str] = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        if self._scope:
            form_data["scope"] = self._scope

        logger.debug("Fetching new client_credentials token from %s", self._token_url)
        with httpx.Client(timeout=15.0) as client:
            response = client.post(self._token_url, data=form_data)
            response.raise_for_status()
            data = response.json()

        expires_in: int = int(data.get("expires_in", 3600))
        token = OAuth2Token(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=time.time() + expires_in,
            token_type=data.get("token_type", "Bearer"),
        )
        logger.debug(
            "Obtained client_credentials token; expires_in=%ds", expires_in
        )
        return token

    def get_valid_token(self) -> str:
        """
        Return a valid access token string, refreshing if the cached token
        has expired. Thread-safe via an internal Lock.

        Returns:
            The raw access token string (ready to use in Authorization header).
        """
        with self._lock:
            if self._cached_token is None or self._cached_token.is_expired():
                logger.info(
                    "Client credentials token expired or absent — refreshing"
                )
                self._cached_token = self.get_token()
            return self._cached_token.access_token


# ─────────────────────────────────────────────────────────
# AUTHORIZATION CODE GRANT
# ─────────────────────────────────────────────────────────

class OAuth2AuthorizationCode:
    """
    Authorization code grant. Used by Salesforce OAuth2 Connected Apps.

    This grant type requires a human to visit an authorization URL in their
    browser, approve the app, and then exchange the returned code for tokens.
    Scout assumes the authorization has already happened and a refresh_token
    is stored in the connector's credentials. This class handles the
    ongoing token refresh lifecycle.

    Stateless: this class does not cache tokens. Pass the stored OAuth2Token
    to get_valid_token() and persist any returned updated token.
    """

    def __init__(
        self,
        token_url: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
    ) -> None:
        self._token_url = token_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri

    def exchange_code(self, code: str) -> OAuth2Token:
        """
        Exchange a one-time authorization code for an access + refresh token.

        Called during the initial OAuth2 setup flow. In production use,
        this is triggered by the OAuth2 callback route after the user
        completes the browser-based authorization step.

        Args:
            code: The authorization code from the callback query string.

        Returns:
            OAuth2Token with both access_token and refresh_token populated.

        Raises:
            httpx.HTTPStatusError on non-2xx responses.
        """
        form_data = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "redirect_uri": self._redirect_uri,
        }
        logger.info("Exchanging authorization code for tokens at %s", self._token_url)
        with httpx.Client(timeout=15.0) as client:
            response = client.post(self._token_url, data=form_data)
            response.raise_for_status()
            data = response.json()

        expires_in = int(data.get("expires_in", 3600))
        return OAuth2Token(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=time.time() + expires_in,
            token_type=data.get("token_type", "Bearer"),
        )

    def refresh(self, refresh_token: str) -> OAuth2Token:
        """
        Use a stored refresh_token to obtain a new access_token.

        Salesforce issues a new access_token (and sometimes a new
        refresh_token) on every refresh call. Callers must persist the
        returned token to avoid losing the refresh_token.

        Args:
            refresh_token: The refresh token from a previous token exchange.

        Returns:
            A new OAuth2Token. The refresh_token field may be updated.

        Raises:
            httpx.HTTPStatusError on invalid or expired refresh tokens.
        """
        form_data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        logger.info("Refreshing OAuth2 access token at %s", self._token_url)
        with httpx.Client(timeout=15.0) as client:
            response = client.post(self._token_url, data=form_data)
            response.raise_for_status()
            data = response.json()

        expires_in = int(data.get("expires_in", 3600))
        # Salesforce may return a new refresh_token; fall back to the old one
        new_refresh = data.get("refresh_token", refresh_token)
        return OAuth2Token(
            access_token=data["access_token"],
            refresh_token=new_refresh,
            expires_at=time.time() + expires_in,
            token_type=data.get("token_type", "Bearer"),
        )

    def get_valid_token(
        self, stored_token: OAuth2Token
    ) -> tuple[str, OAuth2Token]:
        """
        Return a valid access token, refreshing the stored token if expired.

        This is the primary entry point for connectors. They call this on
        every request, passing in the token they last received. If the token
        is still valid, the same token is returned unchanged. If it has
        expired, a refresh is performed and the updated token is returned
        so the caller can persist it.

        Args:
            stored_token: The OAuth2Token currently held by the connector.

        Returns:
            A 2-tuple of (access_token_string, oauth2_token).
            The oauth2_token should be saved if it differs from stored_token.

        Raises:
            httpx.HTTPStatusError if the refresh_token is invalid or revoked.
            ValueError if stored_token has no refresh_token to use.
        """
        if not stored_token.is_expired():
            return stored_token.access_token, stored_token

        if not stored_token.refresh_token:
            raise ValueError(
                "OAuth2 access token is expired and no refresh_token is available. "
                "Re-authorization is required."
            )

        logger.info("Access token expired — refreshing using stored refresh_token")
        new_token = self.refresh(stored_token.refresh_token)
        return new_token.access_token, new_token


# ─────────────────────────────────────────────────────────
# AUTHORIZATION URL HELPER
# ─────────────────────────────────────────────────────────

def build_auth_url(
    auth_url: str,
    client_id: str,
    redirect_uri: str,
    scope: str,
    state: str,
) -> str:
    """
    Build the full authorization URL for the OAuth2 Authorization Code flow.

    The user must be redirected to this URL in their browser to grant consent.
    After approval, the identity provider redirects to redirect_uri with
    `code` and `state` query parameters.

    Args:
        auth_url:     The identity provider's authorization endpoint.
        client_id:    The OAuth2 client (application) ID.
        redirect_uri: Where the IdP should redirect after authorization.
        scope:        Space-separated list of OAuth2 scopes to request.
        state:        A random CSRF-protection value; verify on callback.

    Returns:
        The complete authorization URL with all parameters encoded.

    Example:
        url = build_auth_url(
            auth_url="https://login.salesforce.com/services/oauth2/authorize",
            client_id="3MVG9...",
            redirect_uri="https://scout.example.com/oauth/callback/salesforce",
            scope="api refresh_token offline_access",
            state="abc123xyz",
        )
        # Redirect the user's browser to `url`
    """
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
    }
    return f"{auth_url}?{urlencode(params)}"
