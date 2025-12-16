from typing import TypedDict


class KeyBackupDocument(TypedDict, total=False):
    """
    Stores encrypted key backup for a user.
    The backup contains all conversation AES keys, encrypted with PIN-derived key.
    Only one backup per user is allowed.
    """
    _id: str
    user_id: str                    # User who owns this backup
    encrypted_backup: str           # AES-encrypted JSON containing all session keys (Base64)
    salt: str                       # Salt used for PBKDF2 key derivation (Base64)
    iv: str                         # IV for AES-GCM encryption (Base64)
    conversation_ids: list[str]     # List of conversation IDs included in backup
    created_at: str                 # ISO timestamp
    updated_at: str                 # ISO timestamp
