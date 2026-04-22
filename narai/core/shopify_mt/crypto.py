"""
Fernet encryption for merchant access tokens.

Never log, return, or persist plaintext access tokens. Always go through
these helpers on read/write to `merchants.access_token_encrypted`.

Setup:
  1. Generate once:    python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  2. Add to Railway:   MERCHANT_TOKEN_KEY=<generated_key>
"""
from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken


class MerchantTokenKeyMissing(RuntimeError):
    pass


def _fernet() -> Fernet:
    key = os.getenv("MERCHANT_TOKEN_KEY", "")
    if not key:
        raise MerchantTokenKeyMissing(
            "MERCHANT_TOKEN_KEY env var not set. Generate with Fernet.generate_key()."
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as e:
        raise RuntimeError("Merchant token decrypt failed — key rotation or data corruption?") from e
