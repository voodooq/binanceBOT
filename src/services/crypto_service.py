import logging

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from src.core.config import settings

logger = logging.getLogger(__name__)


class CryptoService:
    """
    Master Key & DEK Management Service
    """

    def __init__(self):
        master_key = self._sanitize_secret(settings.MASTER_ENCRYPTION_KEY)
        if not master_key:
            raise RuntimeError("MASTER_ENCRYPTION_KEY is not set.")

        try:
            self._master_fernet = Fernet(master_key.encode("utf-8"))
        except ValueError as exc:
            logger.critical("MASTER_ENCRYPTION_KEY validation failed during CryptoService initialization")
            raise ValueError(
                "Invalid MASTER_ENCRYPTION_KEY. Must be 32 url-safe base64-encoded bytes."
            ) from exc

        self._ph = PasswordHasher()

    @staticmethod
    def _sanitize_secret(value: str | None) -> str:
        if value is None:
            return ""
        return str(value).strip().strip("'\"")

    def _decrypt_dek(self, encrypted_dek_b64: str) -> bytes:
        if not encrypted_dek_b64 or not encrypted_dek_b64.strip():
            raise ValueError("Invalid DEK: encrypted_dek_b64 is empty")

        try:
            return self._master_fernet.decrypt(encrypted_dek_b64.encode("utf-8"))
        except InvalidToken as exc:
            raise ValueError("Invalid DEK (Master Key mismatch or corrupted payload)") from exc

    # --- PWD Hashing ---
    def hash_password(self, password: str) -> str:
        """Hash a password using Argon2"""
        return self._ph.hash(password)

    def verify_password(self, hashed_password: str, plain_password: str) -> bool:
        """Verify password. Returns False if mismatch"""
        try:
            return self._ph.verify(hashed_password, plain_password)
        except VerifyMismatchError:
            return False

    # --- DEK Management ---
    def generate_user_dek(self) -> tuple[str, str]:
        """
        Generate a Data Encryption Key (DEK) for a user.
        Returns: (plain_dek_str, encrypted_dek_str)
        """
        dek = Fernet.generate_key()
        encrypted_dek = self._master_fernet.encrypt(dek)
        return dek.decode("utf-8"), encrypted_dek.decode("utf-8")

    def encrypt_with_dek(self, plain_dek: str, data: str) -> str:
        """Encrypt user data (like API Secret or TOTP) using their plain DEK"""
        if not plain_dek or not plain_dek.strip():
            raise ValueError("Invalid DEK: plain_dek is empty")
        user_fernet = Fernet(plain_dek.encode("utf-8"))
        return user_fernet.encrypt(data.encode("utf-8")).decode("utf-8")

    def encrypt_secret_with_dek(self, encrypted_dek_b64: str, secret_str: str) -> str:
        """
        信封加密便捷方法：先用主密钥解密用户 DEK，再用 DEK 加密目标秘钥。
        用于绑定 API Key 时加密用户的 API Secret。
        """
        if not secret_str or not secret_str.strip():
            raise ValueError("Secret value is empty")

        dek_bytes = self._decrypt_dek(encrypted_dek_b64)
        user_fernet = Fernet(dek_bytes)
        return user_fernet.encrypt(secret_str.encode("utf-8")).decode("utf-8")

    def decrypt_user_secret(self, encrypted_dek: str, encrypted_secret: str) -> str:
        """
        Decrypt User's DEK with Master Key, then decrypt their Secret with DEK.
        """
        if not encrypted_secret or not encrypted_secret.strip():
            raise ValueError("Encrypted secret is empty")

        dek_bytes = self._decrypt_dek(encrypted_dek)
        user_fernet = Fernet(dek_bytes)
        return user_fernet.decrypt(encrypted_secret.encode("utf-8")).decode("utf-8")


crypto_service = CryptoService()