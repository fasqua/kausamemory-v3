"""Client-side cryptography and content-addressing.

Everything here runs on the user's device. KausaLayer never sees the passphrase,
the key, or the plaintext. Order is deliberate: encrypt first, then address the
ciphertext. Hashing the ciphertext lets any storage node verify the bytes it
holds while the client still verifies end-to-end, so a node is trusted only for
availability, never for integrity.

Blob layout:
    [ magic "KMB1" (4B) ][ nonce (12B) ][ AES-256-GCM( gzip(plaintext) ) + tag ]
Locator:
    blake3:<hex>        self-describing so the hash algorithm can change later
"""

from __future__ import annotations

import gzip
import os

import blake3
from argon2.low_level import Type, hash_secret_raw
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"KMB1"
NONCE_LEN = 12
KEY_LEN = 32  # AES-256


def derive_key(passphrase: str, salt: bytes) -> bytes:
    """Argon2id KDF. Passphrases are low-entropy, so a memory-hard KDF (not a raw
    hash) is required. Salt is non-secret; deriving it from the user's Solana
    pubkey lets the same key reconstruct on every device."""
    return hash_secret_raw(
        secret=passphrase.encode("utf-8"),
        salt=salt,
        time_cost=3,
        memory_cost=64 * 1024,  # 64 MB
        parallelism=4,
        hash_len=KEY_LEN,
        type=Type.ID,
    )


def derive_salt(pubkey: str) -> bytes:
    """Deterministic 16-byte salt from a Solana pubkey (or any stable id)."""
    return blake3.blake3(b"kausamemory-salt:" + pubkey.encode()).digest()[:16]


def encrypt(plaintext: bytes, key: bytes) -> bytes:
    nonce = os.urandom(NONCE_LEN)
    ct = AESGCM(key).encrypt(nonce, gzip.compress(plaintext), MAGIC)
    return MAGIC + nonce + ct


def decrypt(blob: bytes, key: bytes) -> bytes:
    if blob[:4] != MAGIC:
        raise ValueError("bad magic: not a KausaMemory blob")
    nonce = blob[4 : 4 + NONCE_LEN]
    ct = blob[4 + NONCE_LEN :]
    return gzip.decompress(AESGCM(key).decrypt(nonce, ct, MAGIC))


def content_address(ciphertext: bytes) -> str:
    """Locator = blake3 of the ciphertext, self-describing."""
    return "blake3:" + blake3.blake3(ciphertext).hexdigest()


def verify(locator: str, ciphertext: bytes) -> bool:
    algo, _, digest = locator.partition(":")
    if algo != "blake3":
        raise ValueError(f"unsupported locator algorithm: {algo}")
    return blake3.blake3(ciphertext).hexdigest() == digest


def encrypt_deterministic(plaintext: bytes, key: bytes) -> bytes:
    """Deterministic AEAD for chunk dedup: identical (plaintext, key) yields
    identical ciphertext, so an unchanged chunk maps to the same content address
    and is not re-uploaded. The nonce is derived from key and plaintext, so it is
    unique per distinct plaintext. Trade-off: identical chunks appear as identical
    ciphertext, which is inherent to any deduplicating store. decrypt() reads the
    nonce from the blob, so it decrypts these blobs unchanged.
    """
    nonce = blake3.blake3(b"kausamemory-detnonce:" + key + plaintext).digest()[:NONCE_LEN]
    ct = AESGCM(key).encrypt(nonce, gzip.compress(plaintext), MAGIC)
    return MAGIC + nonce + ct
