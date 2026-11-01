"""Pure-Python cryptographic primitives for TP-Link LuCI authentication.

Implements MD5 password hashing, ephemeral AES key/IV generation, AES-128-CBC
encryption/decryption with PKCS7 padding, and 53-byte chunked RSA encryption
matching TP-Link's tpEncrypt.js and encrypt.js.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def md5_hash(username: str = "", password: str = "") -> str:
    """Compute lowercase 32-character MD5 hash of username + password.

    For Archer AX23 and similar routers where username is empty or omitted,
    this hashes only the password (equivalent to md5(password)).
    """
    raw = (username + password).encode("utf-8")
    return hashlib.md5(raw).hexdigest().lower()


def generate_aes_key_iv() -> tuple[str, str]:
    """Generate ephemeral 16-digit ASCII numeric AES-128 key and IV.

    Matches tpEncrypt.js generateRandomIntString(16).
    """
    key = "".join(str(secrets.randbelow(10)) for _ in range(16))
    iv = "".join(str(secrets.randbelow(10)) for _ in range(16))
    return key, iv


def aes_encrypt(plaintext: str, key: str, iv: str) -> str:
    """Encrypt plaintext with AES-128-CBC and PKCS7 padding.

    Returns standard Base64-encoded ASCII ciphertext.
    """
    key_bytes = key.encode("utf-8")
    iv_bytes = iv.encode("utf-8")
    data_bytes = plaintext.encode("utf-8")

    padder = padding.PKCS7(128).padder()
    padded_data = padder.update(data_bytes) + padder.finalize()

    cipher = Cipher(algorithms.AES(key_bytes), modes.CBC(iv_bytes))
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded_data) + encryptor.finalize()

    return base64.b64encode(ciphertext).decode("ascii")


def aes_decrypt(ciphertext_b64: str, key: str, iv: str) -> str:
    """Decrypt Base64-encoded AES-128-CBC ciphertext and remove PKCS7 padding.

    Returns decrypted UTF-8 plaintext string.
    """
    key_bytes = key.encode("utf-8")
    iv_bytes = iv.encode("utf-8")
    ciphertext = base64.b64decode(ciphertext_b64)

    cipher = Cipher(algorithms.AES(key_bytes), modes.CBC(iv_bytes))
    decryptor = cipher.decryptor()
    padded_data = decryptor.update(ciphertext) + decryptor.finalize()

    unpadder = padding.PKCS7(128).unpadder()
    plaintext_bytes = unpadder.update(padded_data) + unpadder.finalize()

    return plaintext_bytes.decode("utf-8")


def rsa_encrypt_chunk(chunk: str | bytes, nn_hex: str, ee_hex: str = "010001") -> str:
    """Encrypt a single chunk (<=53 bytes) with RSA PKCS#1 v1.5 padding.

    Uses pure-Python RFC 2313 PKCS#1 v1.5 padding + modular exponentiation so both
    512-bit (Archer AX23 /login?form=keys) and 1024/2048-bit RSA keys work without
    OpenSSL minimum-key-size exceptions.
    Outputs lowercase hex formatted to the modulus width len(nn_hex).
    """
    nn = int(nn_hex, 16)
    ee = int(ee_hex, 16)
    hex_len = len(nn_hex)
    chunk_bytes = chunk.encode("utf-8") if isinstance(chunk, str) else chunk

    key_bytes = (hex_len + 1) // 2
    ps_len = key_bytes - len(chunk_bytes) - 3
    if ps_len < 8:
        raise ValueError(f"Chunk size {len(chunk_bytes)} bytes too large for key size {key_bytes} bytes")

    ps = bytearray()
    while len(ps) < ps_len:
        raw = secrets.token_bytes(ps_len - len(ps))
        ps.extend(b for b in raw if b != 0)

    em = b"\x00\x02" + bytes(ps) + b"\x00" + chunk_bytes
    c = pow(int.from_bytes(em, "big"), ee, nn)
    return f"{c:0{hex_len}x}"


def rsa_encrypt_pkcs1_v15(
    plaintext: str,
    n_hex: str,
    e_hex: str = "010001",
    chunk_size: int = 53,
) -> str:
    """Encrypt plaintext string using PKCS#1 v1.5 padding and optional chunking.

    Matches TP-Link's pkcs1pad2 implementation in js/all.js and tpEncrypt.min.js.
    When chunk_size > 0, splits UTF-8 encoded plaintext into slices of chunk_size bytes
    to prevent multi-byte characters from overflowing RSA moduli.
    """
    if chunk_size is None or chunk_size <= 0:
        return rsa_encrypt_chunk(plaintext, n_hex, e_hex)

    data_bytes = plaintext.encode("utf-8")
    chunks = [data_bytes[i : i + chunk_size] for i in range(0, len(data_bytes), chunk_size)]
    if not chunks:
        chunks = [b""]

    result = []
    for chunk in chunks:
        result.append(rsa_encrypt_chunk(chunk, n_hex, e_hex))

    return "".join(result)


def rsa_encrypt(plaintext: str, nn_hex: str, ee_hex: str = "010001") -> str:
    """Encrypt plaintext string using 53-byte chunking and RSA PKCS#1 v1.5.

    Splits UTF-8 encoded plaintext into 53-byte slices matching TP-Link tpEncrypt.js.
    """
    return rsa_encrypt_pkcs1_v15(plaintext, nn_hex, ee_hex, chunk_size=53)


def sha256_hash(text: str) -> str:
    """Compute lowercase 64-character SHA-256 hex digest of UTF-8 text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest().lower()


DEFAULT_KEY = "RDpbLfCPsJZ7fiv"  # gitleaks:allow
DEFAULT_DICT = (
    "yLwVl0zKqws7LgKPRQ84Mdt708T1qQ3Ha7xv3H7NyU84p21BriUWBU43odz3iP4r"
    "BL3cD02KZciXTysVXiV8ngg6vL48rPJyAUw0HurW20xqxv9aYb4M9wK1Ae0wlro5"
    "10qXeU07kV57fQMc8L6aLgMLwygtc0F10a0Dg70TOoouyFhdysuRMO51yY5ZlOZZ"
    "LEal1h0t9YQW0Ko7oBwmCAHoic4HYbUyVeU3sfQ1xtXcPcf1aT303wAQhv66qzW"
)


def tp_xor_encrypt(
    a: str,
    b: str = DEFAULT_KEY,
    dic: str = DEFAULT_DICT,
) -> str:
    """TP-Link XOR-scrambling function matching $.su.encrypt in su.fun.js.

    Performs character-by-character XOR with fallback byte 0xBB (187)
    and maps the output to characters in `dic`.
    """
    len1 = len(a)
    len2 = len(b)
    len_dict = len(dic)
    length = max(len1, len2)
    output = []
    for i in range(length):
        cl = ord(a[i]) if i < len1 else 0xBB
        cr = ord(b[i]) if i < len2 else 0xBB
        output.append(dic[(cl ^ cr) % len_dict])
    return "".join(output)


def build_signature(
    password_hash: str,
    seq_with_data_len: int,
    nn_hex: str,
    ee_hex: str = "010001",
    aes_key: str | None = None,
    aes_iv: str | None = None,
    is_login: bool = False,
) -> str:
    """Build and RSA-encrypt LuCI request signature.

    For login requests (is_login=True):
        sign = RSA_ENCRYPT(f"k={aes_key}&i={aes_iv}&h={password_hash}&s={seq_with_data_len}")
    For standard authenticated requests (is_login=False):
        sign = RSA_ENCRYPT(f"h={password_hash}&s={seq_with_data_len}")
    """
    if is_login:
        if not aes_key or not aes_iv:
            raise ValueError("aes_key and aes_iv are required when is_login=True")
        plaintext = f"k={aes_key}&i={aes_iv}&h={password_hash}&s={seq_with_data_len}"
    else:
        plaintext = f"h={password_hash}&s={seq_with_data_len}"

    return rsa_encrypt(plaintext, nn_hex, ee_hex)
