"""Unit tests for tpluci pure-Python crypto engine."""

import json
import pytest
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from tpluci.crypto import (
    aes_decrypt,
    aes_encrypt,
    build_signature,
    generate_aes_key_iv,
    md5_hash,
    rsa_encrypt,
    rsa_encrypt_chunk,
)


@pytest.fixture(scope="module")
def rsa_test_key():
    """Generate a test RSA 1024-bit private key for decryption validation."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    public_numbers = private_key.public_key().public_numbers()
    nn_hex = f"{public_numbers.n:0256x}"
    ee_hex = f"{public_numbers.e:06x}"
    return private_key, nn_hex, ee_hex


def test_md5_hash():
    # Empty username
    h1 = md5_hash("", "supersecret")
    assert len(h1) == 32
    assert h1 == md5_hash(password="supersecret")
    # Non-empty username
    h2 = md5_hash("admin", "supersecret")
    assert len(h2) == 32
    assert h1 != h2


def test_generate_aes_key_iv():
    key, iv = generate_aes_key_iv()
    assert len(key) == 16
    assert len(iv) == 16
    assert key.isdigit()
    assert iv.isdigit()
    # Randomness check across multiple calls
    key2, iv2 = generate_aes_key_iv()
    assert key != key2 or iv != iv2


def test_aes_encrypt_decrypt_roundtrip_short():
    key, iv = generate_aes_key_iv()
    plain = "operation=read"
    enc = aes_encrypt(plain, key, iv)
    assert isinstance(enc, str)
    dec = aes_decrypt(enc, key, iv)
    assert dec == plain


def test_aes_encrypt_decrypt_roundtrip_16byte_boundary():
    key, iv = generate_aes_key_iv()
    plain = "1234567890123456"  # Exactly 16 bytes
    enc = aes_encrypt(plain, key, iv)
    dec = aes_decrypt(enc, key, iv)
    assert dec == plain

    plain32 = "1234567890123456" * 2  # Exactly 32 bytes
    enc32 = aes_encrypt(plain32, key, iv)
    dec32 = aes_decrypt(enc32, key, iv)
    assert dec32 == plain32


def test_aes_encrypt_decrypt_roundtrip_multikilobyte_json():
    key, iv = generate_aes_key_iv()
    payload = {
        "success": True,
        "data": {
            "devices": [
                {
                    "hostname": f"device-{i}",
                    "ip": f"192.168.7.{i}",
                    "mac": f"00:11:22:33:44:{i:02x}",
                }
                for i in range(100)
            ]
        },
    }
    plain = json.dumps(payload)
    assert len(plain) > 5000
    enc = aes_encrypt(plain, key, iv)
    dec = aes_decrypt(enc, key, iv)
    assert dec == plain
    assert json.loads(dec) == payload


def test_rsa_encrypt_under_53_chars(rsa_test_key):
    priv, nn_hex, ee_hex = rsa_test_key
    chunk = "h=5f4dcc3b5aa765d61d8327deb882cf99&s=100"
    assert len(chunk) < 53
    enc = rsa_encrypt(chunk, nn_hex, ee_hex)
    # 1024-bit key = 256 hex chars
    assert len(enc) == len(nn_hex)
    # Decrypt and verify
    raw_ct = bytes.fromhex(enc)
    decrypted = priv.decrypt(raw_ct, padding.PKCS1v15()).decode("utf-8")
    assert decrypted == chunk


def test_rsa_encrypt_exact_53_chars(rsa_test_key):
    priv, nn_hex, ee_hex = rsa_test_key
    chunk = "a" * 53
    enc = rsa_encrypt(chunk, nn_hex, ee_hex)
    assert len(enc) == len(nn_hex)
    raw_ct = bytes.fromhex(enc)
    decrypted = priv.decrypt(raw_ct, padding.PKCS1v15()).decode("utf-8")
    assert decrypted == chunk


def test_rsa_encrypt_multi_chunk(rsa_test_key):
    priv, nn_hex, ee_hex = rsa_test_key
    # 120 chars = 3 chunks (53 + 53 + 14)
    plain = "k=1234567890123456&i=6543210987654321&h=5f4dcc3b5aa765d61d8327deb882cf99&s=123456789012345678901234567890_extra_chars"
    assert len(plain) > 53 * 2
    enc = rsa_encrypt(plain, nn_hex, ee_hex)
    # Must be 3 blocks of 256 hex chars
    assert len(enc) == 3 * len(nn_hex)

    # Decrypt each 256-hex block
    hex_len = len(nn_hex)
    decrypted_parts = []
    for i in range(0, len(enc), hex_len):
        block_hex = enc[i : i + hex_len]
        raw_ct = bytes.fromhex(block_hex)
        part = priv.decrypt(raw_ct, padding.PKCS1v15()).decode("utf-8")
        decrypted_parts.append(part)
    assert "".join(decrypted_parts) == plain


def test_build_signature_login_and_subsequent(rsa_test_key):
    priv, nn_hex, ee_hex = rsa_test_key
    pwd_hash = md5_hash("", "routerpass")
    key, iv = generate_aes_key_iv()

    # Login signature
    sign_login = build_signature(
        password_hash=pwd_hash,
        seq_with_data_len=1050,
        nn_hex=nn_hex,
        ee_hex=ee_hex,
        aes_key=key,
        aes_iv=iv,
        is_login=True,
    )
    assert len(sign_login) >= len(nn_hex)
    assert len(sign_login) % len(nn_hex) == 0

    # Decrypt login signature chunks
    hex_len = len(nn_hex)
    login_parts = []
    for i in range(0, len(sign_login), hex_len):
        raw_ct = bytes.fromhex(sign_login[i : i + hex_len])
        login_parts.append(priv.decrypt(raw_ct, padding.PKCS1v15()).decode("utf-8"))
    login_plain = "".join(login_parts)
    assert login_plain == f"k={key}&i={iv}&h={pwd_hash}&s=1050"

    # Subsequent request signature (no key/iv)
    sign_call = build_signature(
        password_hash=pwd_hash,
        seq_with_data_len=1080,
        nn_hex=nn_hex,
        ee_hex=ee_hex,
        is_login=False,
    )
    assert len(sign_call) == len(nn_hex)
    raw_ct_call = bytes.fromhex(sign_call)
    call_plain = priv.decrypt(raw_ct_call, padding.PKCS1v15()).decode("utf-8")
    assert call_plain == f"h={pwd_hash}&s=1080"


def test_build_signature_missing_keys_raises():
    with pytest.raises(ValueError, match="aes_key and aes_iv are required"):
        build_signature(
            password_hash="testhash",
            seq_with_data_len=100,
            nn_hex="A" * 256,
            is_login=True,
        )


def test_rsa_encrypt_multibyte_utf8_password(rsa_test_key):
    priv, nn_hex, ee_hex = rsa_test_key
    # 30 multi-byte characters = 60 UTF-8 bytes (> 53 byte chunk limit)
    utf8_pwd = "éüñ" * 10
    assert len(utf8_pwd) == 30
    assert len(utf8_pwd.encode("utf-8")) == 60

    enc = rsa_encrypt(utf8_pwd, nn_hex, ee_hex)
    hex_len = len(nn_hex)
    assert len(enc) == 2 * hex_len

    decrypted_bytes = b""
    for i in range(0, len(enc), hex_len):
        raw_ct = bytes.fromhex(enc[i : i + hex_len])
        decrypted_bytes += priv.decrypt(raw_ct, padding.PKCS1v15())
    assert decrypted_bytes.decode("utf-8") == utf8_pwd
