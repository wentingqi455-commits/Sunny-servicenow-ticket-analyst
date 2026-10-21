"""Settings, read from environment variables (or a local .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv(path: Path = Path(".env")) -> None:
    """Minimal .env loader so users don't need an extra package.

    Lines look like KEY=value. Existing environment variables win.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_list(name: str, default: str) -> list[str]:
    return [p.strip() for p in _env(name, default).split(",") if p.strip()]


@dataclass
class Settings:
    # ServiceNow
    instance_url: str = ""
    client_id: str = ""
    client_secret: str = ""
    username: str = ""
    password: str = ""
    grant_type: str = "password"
    tables: list[str] = field(default_factory=list)
    days: int = 7
    verify_ssl: bool = True

    # Hardware barcode
    hardware_categories: list[str] = field(default_factory=list)
    barcode_fields: list[str] = field(default_factory=list)
    barcode_lengths: list[int] = field(default_factory=lambda: [8, 14])

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1"
    openai_base_url: str = ""

    # Output
    output_dir: str = "output"

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv()
        return cls(
            instance_url=_env("SN_INSTANCE_URL").rstrip("/"),
            client_id=_env("SN_CLIENT_ID"),
            client_secret=_env("SN_CLIENT_SECRET"),
            username=_env("SN_USERNAME"),
            password=_env("SN_PASSWORD"),
            grant_type=_env("SN_GRANT_TYPE", "password"),
            tables=_env_list("SN_TABLES", "incident,sc_req_item,problem,change_request"),
            days=int(_env("SN_DAYS", "7")),
            verify_ssl=_env("SN_VERIFY_SSL", "true").lower() != "false",
            hardware_categories=[c.lower() for c in _env_list("HARDWARE_CATEGORIES", "hardware")],
            barcode_fields=_env_list("BARCODE_FIELDS", "cmdb_ci.asset_tag,cmdb_ci.serial_number"),
            barcode_lengths=[int(n) for n in _env_list("BARCODE_LENGTHS", "8,14")],
            openai_api_key=_env("OPENAI_API_KEY"),
            openai_model=_env("OPENAI_MODEL", "gpt-4.1"),
            openai_base_url=_env("OPENAI_BASE_URL"),
            output_dir=_env("OUTPUT_DIR", "output"),
        )

    def missing_servicenow(self) -> list[str]:
        needed = {
            "SN_INSTANCE_URL": self.instance_url,
            "SN_CLIENT_ID": self.client_id,
            "SN_CLIENT_SECRET": self.client_secret,
        }
        if self.grant_type == "password":
            needed["SN_USERNAME"] = self.username
            needed["SN_PASSWORD"] = self.password
        return [k for k, v in needed.items() if not v]
