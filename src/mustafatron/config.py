"""Runtime configuration, read from environment variables or a local ``.env`` file.

Nothing secret is ever written in this module. See ``.env.example`` for every setting.
"""

from functools import lru_cache
from urllib.parse import unquote

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_LEAGUE_ID = 763471


class MissingSecretError(RuntimeError):
    """A setting needed for this operation is not configured."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    league_id: int = Field(DEFAULT_LEAGUE_ID, description="ESPN league to operate on.")
    espn_swid: SecretStr | None = Field(None, description="ESPN `SWID` cookie, including braces.")
    espn_s2: SecretStr | None = Field(None, description="ESPN `espn_s2` cookie, URL-encoded or not.")
    manager_id_key: SecretStr | None = Field(
        None, description="HMAC key that turns SWIDs into the opaque manager IDs stored in data/raw/."
    )

    @field_validator("espn_s2")
    @classmethod
    def _decode_espn_s2(cls, v: SecretStr | None) -> SecretStr | None:
        # Browsers show the cookie URL-encoded (%2B, %2F); requests needs it decoded.
        # Normalizing here means call sites never have to think about it.
        if v is None:
            return None
        return SecretStr(unquote(v.get_secret_value().strip()))

    @field_validator("espn_swid")
    @classmethod
    def _normalize_swid(cls, v: SecretStr | None) -> SecretStr | None:
        if v is None:
            return None
        swid = v.get_secret_value().strip().upper()
        if not swid.startswith("{"):
            swid = "{" + swid + "}"
        return SecretStr(swid)

    def espn_cookies(self) -> dict[str, str]:
        """Cookies for authenticated ESPN API requests."""
        if self.espn_swid is None or self.espn_s2 is None:
            raise MissingSecretError(
                "ESPN_SWID and ESPN_S2 must be set (in .env or the environment) to fetch from ESPN. "
                "See .env.example for how to copy them from your browser."
            )
        return {"swid": self.espn_swid.get_secret_value(), "espn_s2": self.espn_s2.get_secret_value()}

    def manager_key(self) -> bytes:
        if self.manager_id_key is None:
            raise MissingSecretError(
                "MANAGER_ID_KEY must be set to pseudonymize SWIDs before they are written to data/raw/."
            )
        return self.manager_id_key.get_secret_value().encode()


@lru_cache
def get_settings() -> Settings:
    return Settings()
