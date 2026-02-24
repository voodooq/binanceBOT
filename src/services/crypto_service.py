import base64
from cryptography.fernet import Fernet
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from src.core.config import settings

class CryptoService:
    """
    Master Key & DEK Management Service
    """
    def __init__(self):
        master_key = settings.MASTER_ENCRYPTION_KEY
        if not master_key:
            raise RuntimeError("MASTER_ENCRYPTION_KEY is not set.")
        # Ensure it's valid format for Fernet
        # Fernet takes urlsafe-base64-encoded 32-byte key
        self._master_fernet = Fernet(master_key.encode())
        self._ph = PasswordHasher()

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
        return dek.decode(), encrypted_dek.decode()

    def encrypt_with_dek(self, plain_dek: str, data: str) -> str:
        """Encrypt user data (like API Secret or TOTP) using their plain DEK"""
        user_fernet = Fernet(plain_dek.encode())
        return user_fernet.encrypt(data.encode()).decode()

    def decrypt_user_secret(self, encrypted_dek: str, encrypted_secret: str) -> str:
        """
        Decrypt User's DEK with Master Key, then decrypt their Secret with DEK.
        """
        # 1. Decrypt DEK
        dek_bytes = self._master_fernet.decrypt(encrypted_dek.encode())
        user_fernet = Fernet(dek_bytes)
        # 2. Decrypt Secret
        return user_fernet.decrypt(encrypted_secret.encode()).decode()

crypto_service = CryptoService()
