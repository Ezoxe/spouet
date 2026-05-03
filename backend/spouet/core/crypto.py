"""Chiffrement symétrique pour le coffre de secrets.

Le coffre dérive sa clé Fernet de `settings.secret_key` via HKDF-SHA256.
Cela permet de ne pas stocker une seconde clé dans la config : tout repose sur
`SPOUET_SECRET_KEY`. Conséquence : faire tourner `secret_key` invalide tous les
secrets existants — utiliser `spouet-admin secrets rotate` pour rechiffrer.
"""

from __future__ import annotations

import base64
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from spouet.core.config import settings


class SecretDecryptionError(RuntimeError):
    """Raised lorsqu'un secret stocké ne peut être déchiffré (clé changée ?)."""


def _derive_fernet_key(secret: str, salt: bytes = b"spouet.secrets.v1") -> bytes:
    raw = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=b"spouet/secrets-vault",
    ).derive(secret.encode("utf-8"))
    return base64.urlsafe_b64encode(raw)


@lru_cache(maxsize=1)
def _vault() -> MultiFernet:
    primary = Fernet(_derive_fernet_key(settings.secret_key))
    return MultiFernet([primary])


def encrypt(plaintext: str) -> str:
    return _vault().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(ciphertext: str) -> str:
    try:
        return _vault().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as e:
        raise SecretDecryptionError(
            "Impossible de déchiffrer (SPOUET_SECRET_KEY a peut-être changé)"
        ) from e
