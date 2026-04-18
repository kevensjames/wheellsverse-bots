"""Local-first encrypted file storage using Fernet (AES-128-CBC + HMAC-SHA256).
Key is derived from NARAI_STORAGE_KEY env var. Never leaves the machine."""
import base64
import json
import os
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ROOT = Path(__file__).parent.parent
_STORE_DIR = ROOT / "data" / "encrypted"
_STORE_DIR.mkdir(parents=True, exist_ok=True)

_SALT = b"narai_wheellsverse_2026"  # fixed salt; key is the secret


def _fernet() -> Fernet:
    raw = os.getenv("NARAI_STORAGE_KEY", "").encode()
    if not raw:
        raise EnvironmentError("NARAI_STORAGE_KEY not set in .env")
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=_SALT, iterations=480_000)
    key = base64.urlsafe_b64encode(kdf.derive(raw))
    return Fernet(key)


def write(name: str, data: Any) -> Path:
    """Encrypt and persist data. Returns the storage path."""
    payload = json.dumps(data, default=str).encode()
    token = _fernet().encrypt(payload)
    path = _STORE_DIR / f"{name}.enc"
    path.write_bytes(token)
    return path


def read(name: str) -> Any:
    """Decrypt and return data. Raises FileNotFoundError if not found."""
    path = _STORE_DIR / f"{name}.enc"
    if not path.exists():
        raise FileNotFoundError(f"No encrypted file: {name}")
    token = path.read_bytes()
    payload = _fernet().decrypt(token)
    return json.loads(payload)


def delete(name: str) -> None:
    path = _STORE_DIR / f"{name}.enc"
    if path.exists():
        path.unlink()


def list_keys() -> list[str]:
    return [p.stem for p in _STORE_DIR.glob("*.enc")]
