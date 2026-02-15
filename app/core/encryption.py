from cryptography.fernet import Fernet, InvalidToken
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

_fernet = None


def get_fernet() -> Fernet:
    """Get Fernet instance using the ENCRYPTION_KEY from settings."""
    global _fernet
    if _fernet is None:
        key = settings.ENCRYPTION_KEY
        if not key:
            raise ValueError(
                "ENCRYPTION_KEY is not set. Generate one with: "
                "python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
            )
        _fernet = Fernet(key.encode())
    return _fernet


def encrypt_value(plain_text: str) -> str:
    """Encrypt a string value. Returns base64-encoded ciphertext."""
    if not plain_text:
        return ""
    f = get_fernet()
    return f.encrypt(plain_text.encode()).decode()


def decrypt_value(cipher_text: str) -> str:
    """Decrypt a base64-encoded ciphertext. Returns plain string."""
    if not cipher_text:
        return ""
    f = get_fernet()
    try:
        return f.decrypt(cipher_text.encode()).decode()
    except InvalidToken:
        logger.error("Failed to decrypt value — invalid token or key mismatch")
        raise ValueError("Failed to decrypt value. The encryption key may have changed.")
