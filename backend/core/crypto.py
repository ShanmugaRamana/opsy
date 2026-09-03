import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet

logger = logging.getLogger("crypto")

SECRET_KEY_PATH = Path.home() / ".local" / "share" / "opsy" / "secret.key"


def _load_or_create_key() -> bytes:
    if SECRET_KEY_PATH.exists():
        return SECRET_KEY_PATH.read_bytes()

    SECRET_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()

    fd = os.open(SECRET_KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key)

    logger.info(f"generated new secret key at {SECRET_KEY_PATH}")
    return key


_fernet = Fernet(_load_or_create_key())


def encrypt(plaintext: str) -> str:
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _fernet.decrypt(ciphertext.encode()).decode()
