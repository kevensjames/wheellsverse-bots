"""
NarAI Godmode - Encrypted credential vault.
Stores per-service credentials (password OR api_token) encrypted with Fernet.
Master key lives in env var NARAI_VAULT_KEY. Never commit that key.
"""
import os
import json
import base64
import sqlite3
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


DEFAULT_DB = Path.home() / ".narai" / "vault.db"


def _derive_key(master_password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=390_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(master_password.encode()))


class Vault:
    """Encrypted credential store. One row per service."""

    def __init__(self, db_path: Path = DEFAULT_DB, master_password: str | None = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

        master = master_password or os.environ.get("NARAI_VAULT_KEY")
        if not master:
            raise RuntimeError(
                "Set NARAI_VAULT_KEY env var or pass master_password. "
                "Generate one with: python -c \"import secrets;print(secrets.token_urlsafe(32))\""
            )

        self.salt = self._get_or_create_salt()
        self.fernet = Fernet(_derive_key(master, self.salt))

    # --- internal ---

    def _init_db(self) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value BLOB
            );
            CREATE TABLE IF NOT EXISTS credentials (
                service TEXT PRIMARY KEY,
                kind TEXT NOT NULL,          -- 'password' | 'api_token' | 'oauth'
                blob BLOB NOT NULL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.commit()
        conn.close()

    def _get_or_create_salt(self) -> bytes:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute("SELECT value FROM meta WHERE key='salt'").fetchone()
        if row:
            salt = row[0]
        else:
            salt = os.urandom(16)
            conn.execute("INSERT INTO meta(key, value) VALUES('salt', ?)", (salt,))
            conn.commit()
        conn.close()
        return salt

    # --- public API ---

    def set_password(self, service: str, username: str, password: str, **extra) -> None:
        self._write(service, "password", {"username": username, "password": password, "extra": extra})

    def set_token(self, service: str, token: str, **extra) -> None:
        self._write(service, "api_token", {"token": token, "extra": extra})

    def get(self, service: str) -> dict | None:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT kind, blob FROM credentials WHERE service=?", (service.lower(),)
        ).fetchone()
        conn.close()
        if not row:
            return None
        kind, blob = row
        data = json.loads(self.fernet.decrypt(blob).decode())
        data["kind"] = kind
        return data

    def list_services(self) -> list[tuple[str, str]]:
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute("SELECT service, kind FROM credentials ORDER BY service").fetchall()
        conn.close()
        return rows

    def delete(self, service: str) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM credentials WHERE service=?", (service.lower(),))
        conn.commit()
        conn.close()

    # --- internal write ---

    def _write(self, service: str, kind: str, payload: dict) -> None:
        blob = self.fernet.encrypt(json.dumps(payload).encode())
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            INSERT INTO credentials(service, kind, blob) VALUES(?, ?, ?)
            ON CONFLICT(service) DO UPDATE SET
                kind=excluded.kind,
                blob=excluded.blob,
                updated_at=CURRENT_TIMESTAMP
            """,
            (service.lower(), kind, blob),
        )
        conn.commit()
        conn.close()
