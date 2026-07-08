"""密码哈希与校验工具。

使用 PBKDF2-HMAC-SHA256 算法，迭代次数 600_000 次，符合 OWASP 2023 推荐值。
哈希格式：pbkdf2_sha256$<iterations>$<salt_b64>$<digest_b64>
该格式与 Django 的 PBKDF2PasswordHasher 兼容，便于将来迁移。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from secrets import token_bytes


PBKDF2_ALGORITHM = "sha256"
# 迭代次数越高越安全，但会增加登录 CPU 开销；当前值为 OWASP 2023 推荐的最低值
PBKDF2_ITERATIONS = 600_000
PBKDF2_SALT_BYTES = 16


def hash_password(password: str) -> str:
    """将明文密码哈希为存储格式的字符串。每次调用生成新的随机盐，结果不可重复。"""
    salt = token_bytes(PBKDF2_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        PBKDF2_ALGORITHM,
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    salt_part = base64.urlsafe_b64encode(salt).decode("utf-8").rstrip("=")
    digest_part = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
    return f"pbkdf2_{PBKDF2_ALGORITHM}${PBKDF2_ITERATIONS}${salt_part}${digest_part}"


def verify_password(password: str, encoded_password: str) -> bool:
    """校验明文密码是否与存储的哈希匹配。

    使用 hmac.compare_digest 进行常数时间比较，防止时序攻击。
    格式不匹配时静默返回 False，不暴露具体原因。
    """
    try:
        scheme, iterations_raw, salt_part, digest_part = encoded_password.split("$", 3)
    except ValueError:
        return False

    if not scheme.startswith("pbkdf2_"):
        return False

    algorithm = scheme.removeprefix("pbkdf2_")
    try:
        iterations = int(iterations_raw)
    except ValueError:
        return False

    salt = _decode_base64(salt_part)
    expected_digest = _decode_base64(digest_part)
    if salt is None or expected_digest is None:
        return False

    actual_digest = hashlib.pbkdf2_hmac(
        algorithm,
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual_digest, expected_digest)


def _decode_base64(value: str) -> bytes | None:
    """解码 URL-safe Base64 字符串，自动补齐缺失的填充字符 '='。"""
    remainder = len(value) % 4
    if remainder:
        value = value + ("=" * (4 - remainder))
    try:
        return base64.urlsafe_b64decode(value.encode("utf-8"))
    except (ValueError, TypeError):
        return None
