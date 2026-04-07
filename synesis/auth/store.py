from __future__ import annotations

import json
import os
from cryptography.fernet import Fernet
from pathlib import Path


class AuthStore:
    def __init__(self, base_dir: str | Path):
        self.dir = Path(base_dir) / ".auth"
        self._fernet: Fernet | None = None

    def init(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.dir, 0o700)
        key_file = self.dir / ".key"

        if key_file.exists():
            key = key_file.read_bytes()
        else:
            key = Fernet.generate_key()
            key_file.write_bytes(key)
            os.chmod(key_file, 0o600)

        self._fernet = Fernet(key)

    def save(self, provider: str, tokens: dict) -> None:
        if not self._fernet:
            raise RuntimeError("AuthStore not initialized")

        data = json.dumps(tokens).encode()
        encrypted = self._fernet.encrypt(data)
        (self.dir / f"{provider}.enc").write_bytes(encrypted)

    def load(self, provider: str) -> dict | None:
        if not self._fernet:
            raise RuntimeError("AuthStore not initialized")

        path = self.dir / f"{provider}.enc"
        if not path.exists():
            return None

        try:
            encrypted = path.read_bytes()
            decrypted = self._fernet.decrypt(encrypted)
            return json.loads(decrypted)
        except Exception:
            return None

    def delete(self, provider: str) -> bool:
        path = self.dir / f"{provider}.enc"
        if path.exists():
            path.unlink()
            return True
        return False

    def list(self) -> list[str]:
        if not self.dir.exists():
            return []
        return [f.stem for f in self.dir.glob("*.enc")]
