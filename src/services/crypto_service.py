import base64
from cryptography.fernet import Fernet, InvalidToken
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
        
        # 预处理：确保是字符串并彻底剥离引号/空格
        master_key = str(master_key).strip().strip("'\"")
        
        try:
            self._master_fernet = Fernet(master_key.encode())
        except ValueError as e:
            # 增加调试信息：到底传进去了多长、什么样格式的秘钥
            key_len = len(master_key)
            print(f"CRITICAL: MASTER_ENCRYPTION_KEY validation failed! Length: {key_len}")
            # 重新抛出，带上更多线索
            raise ValueError(f"Invalid MASTER_ENCRYPTION_KEY (Length: {key_len}). Must be 32 url-safe base64-encoded bytes.") from e
            
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

    def encrypt_secret_with_dek(self, encrypted_dek_b64: str, secret_str: str) -> str:
        """
        信封加密便捷方法：先用主密钥解密用户 DEK，再用 DEK 加密目标秘钥。
        用于绑定 API Key 时加密用户的 API Secret。
        """
        # 1. 用主密钥解开用户的 DEK
        try:
            dek_bytes = self._master_fernet.decrypt(encrypted_dek_b64.encode())
        except InvalidToken:
            raise ValueError("Invalid DEK (Master Key might have changed)")
        # 2. 用 DEK 加密目标数据
        user_fernet = Fernet(dek_bytes)
        return user_fernet.encrypt(secret_str.encode()).decode()

    def decrypt_user_secret(self, encrypted_dek: str, encrypted_secret: str) -> str:
        """
        Decrypt User's DEK with Master Key, then decrypt their Secret with DEK.
        """
        # 1. Decrypt DEK
        try:
            dek_bytes = self._master_fernet.decrypt(encrypted_dek.encode())
        except InvalidToken:
            raise ValueError("Invalid DEK (Master Key might have changed)")
        user_fernet = Fernet(dek_bytes)
        # 2. Decrypt Secret
        return user_fernet.decrypt(encrypted_secret.encode()).decode()

crypto_service = CryptoService()
