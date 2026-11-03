"""Secrets Management System - Secure storage and retrieval of sensitive data."""

import os
import json
import logging
from typing import Any, Dict, Optional
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from abc import ABC, abstractmethod
import base64

try:
    from cryptography.fernet import Fernet
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class Secret:
    """Represents a secret value."""

    name: str
    value: str
    secret_type: str  # api_key, password, token, connection_string, etc.
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    description: str = ""
    tags: list = field(default_factory=list)
    is_encrypted: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


class SecretsBackend(ABC):
    """Abstract base class for secrets backend."""

    @abstractmethod
    def store(self, secret: Secret) -> None:
        """Store a secret."""
        pass

    @abstractmethod
    def retrieve(self, name: str) -> Optional[Secret]:
        """Retrieve a secret by name."""
        pass

    @abstractmethod
    def delete(self, name: str) -> bool:
        """Delete a secret."""
        pass

    @abstractmethod
    def list_secrets(self) -> list[str]:
        """List all secret names."""
        pass


class FileSecretsBackend(SecretsBackend):
    """File-based secrets storage (for development)."""

    def __init__(self, base_path: str = "secrets", encrypt: bool = False):
        """Initialize file secrets backend.

        Args:
            base_path: Base directory for secrets files
            encrypt: Whether to encrypt secrets with Fernet
        """
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.encrypt = encrypt
        self.cipher = None

        if encrypt and CRYPTO_AVAILABLE:
            key_file = self.base_path / ".key"
            if key_file.exists():
                with open(key_file, "rb") as f:
                    self.cipher = Fernet(f.read())
            else:
                key = Fernet.generate_key()
                with open(key_file, "wb") as f:
                    f.write(key)
                self.cipher = Fernet(key)
                logger.warning(f"Generated new encryption key at {key_file}")

    def _get_secret_path(self, name: str) -> Path:
        """Get file path for secret."""
        return self.base_path / f"{name}.json"

    def store(self, secret: Secret) -> None:
        """Store a secret."""
        data = {
            "name": secret.name,
            "value": secret.value,
            "secret_type": secret.secret_type,
            "created_at": secret.created_at,
            "updated_at": datetime.utcnow().isoformat(),
            "description": secret.description,
            "tags": secret.tags,
            "is_encrypted": self.encrypt,
            "metadata": secret.metadata,
        }

        # Encrypt value if enabled
        if self.encrypt and self.cipher and CRYPTO_AVAILABLE:
            data["value"] = self.cipher.encrypt(secret.value.encode()).decode()
            data["is_encrypted"] = True

        path = self._get_secret_path(secret.name)

        with open(path, "w") as f:
            json.dump(data, f, indent=2)

        # Set restrictive permissions (Unix-like systems)
        try:
            os.chmod(path, 0o600)
        except:
            pass

        logger.info(f"Stored secret: {secret.name}")

    def retrieve(self, name: str) -> Optional[Secret]:
        """Retrieve a secret."""
        path = self._get_secret_path(name)

        if not path.exists():
            logger.warning(f"Secret not found: {name}")
            return None

        try:
            with open(path) as f:
                data = json.load(f)

            value = data["value"]

            # Decrypt if encrypted
            if data.get("is_encrypted") and self.cipher and CRYPTO_AVAILABLE:
                value = self.cipher.decrypt(value.encode()).decode()

            return Secret(
                name=data["name"],
                value=value,
                secret_type=data["secret_type"],
                created_at=data.get("created_at"),
                updated_at=data.get("updated_at"),
                description=data.get("description", ""),
                tags=data.get("tags", []),
                is_encrypted=data.get("is_encrypted", False),
                metadata=data.get("metadata", {}),
            )
        except Exception as e:
            logger.error(f"Error retrieving secret {name}: {e}")
            return None

    def delete(self, name: str) -> bool:
        """Delete a secret."""
        path = self._get_secret_path(name)

        if not path.exists():
            return False

        try:
            path.unlink()
            logger.info(f"Deleted secret: {name}")
            return True
        except Exception as e:
            logger.error(f"Error deleting secret {name}: {e}")
            return False

    def list_secrets(self) -> list[str]:
        """List all secret names."""
        names = []
        for file in self.base_path.glob("*.json"):
            if file.name != ".key":
                names.append(file.stem)
        return names


class EnvironmentSecretsBackend(SecretsBackend):
    """Environment variable-based secrets (for production)."""

    def __init__(self, prefix: str = "APP_"):
        """Initialize environment secrets backend.

        Args:
            prefix: Environment variable prefix
        """
        self.prefix = prefix

    def _get_env_var_name(self, name: str) -> str:
        """Get environment variable name."""
        return f"{self.prefix}{name.upper()}"

    def store(self, secret: Secret) -> None:
        """Store a secret (sets environment variable)."""
        env_var = self._get_env_var_name(secret.name)
        os.environ[env_var] = secret.value
        logger.info(f"Stored secret in environment: {env_var}")

    def retrieve(self, name: str) -> Optional[Secret]:
        """Retrieve a secret from environment."""
        env_var = self._get_env_var_name(name)
        value = os.environ.get(env_var)

        if not value:
            logger.warning(f"Secret not found in environment: {env_var}")
            return None

        return Secret(
            name=name,
            value=value,
            secret_type="env_var",
            description=f"From environment variable {env_var}",
        )

    def delete(self, name: str) -> bool:
        """Delete a secret from environment."""
        env_var = self._get_env_var_name(name)
        if env_var in os.environ:
            del os.environ[env_var]
            logger.info(f"Deleted secret from environment: {env_var}")
            return True
        return False

    def list_secrets(self) -> list[str]:
        """List all secrets in environment."""
        names = []
        for key in os.environ:
            if key.startswith(self.prefix):
                names.append(key[len(self.prefix):].lower())
        return names


class SecretsManager:
    """Central secrets manager."""

    def __init__(self, backend: Optional[SecretsBackend] = None):
        """Initialize secrets manager.

        Args:
            backend: Secrets backend (defaults to file-based)
        """
        self.backend = backend or FileSecretsBackend(encrypt=True)
        self._cache: Dict[str, Secret] = {}

    def store_secret(
        self,
        name: str,
        value: str,
        secret_type: str = "generic",
        description: str = "",
        tags: Optional[list] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Store a secret.

        Args:
            name: Secret name
            value: Secret value
            secret_type: Type of secret
            description: Description
            tags: Optional tags
            metadata: Optional metadata
        """
        secret = Secret(
            name=name,
            value=value,
            secret_type=secret_type,
            description=description,
            tags=tags or [],
            metadata=metadata or {},
        )

        self.backend.store(secret)
        self._cache[name] = secret

    def get_secret(self, name: str) -> Optional[str]:
        """Get secret value by name.

        Args:
            name: Secret name

            Returns:
            Secret value or None
        """
        # Check cache first
        if name in self._cache:
            return self._cache[name].value

        # Retrieve from backend
        secret = self.backend.retrieve(name)
        if secret:
            self._cache[name] = secret
            return secret.value

        return None

    def get_secret_object(self, name: str) -> Optional[Secret]:
        """Get full secret object."""
        if name in self._cache:
            return self._cache[name]

        secret = self.backend.retrieve(name)
        if secret:
            self._cache[name] = secret
        return secret

    def delete_secret(self, name: str) -> bool:
        """Delete a secret."""
        success = self.backend.delete(name)
        if success and name in self._cache:
            del self._cache[name]
        return success

    def list_secrets(self, secret_type: Optional[str] = None) -> list[str]:
        """List secret names, optionally filtered by type."""
        names = self.backend.list_secrets()

        if secret_type:
            filtered = []
            for name in names:
                secret = self.get_secret_object(name)
                if secret and secret.secret_type == secret_type:
                    filtered.append(name)
            return filtered

        return names

    def update_secret(self, name: str, value: str) -> None:
        """Update a secret value."""
        secret = self.get_secret_object(name)
        if secret:
            secret.value = value
            secret.updated_at = datetime.utcnow().isoformat()
            self.backend.store(secret)
            self._cache[name] = secret
            logger.info(f"Updated secret: {name}")
        else:
            raise ValueError(f"Secret not found: {name}")

    def get_secrets_by_tag(self, tag: str) -> Dict[str, str]:
        """Get all secrets with a specific tag."""
        result = {}
        for name in self.backend.list_secrets():
            secret = self.get_secret_object(name)
            if secret and tag in secret.tags:
                result[name] = secret.value
        return result

    def export_secrets_metadata(self, path: str) -> None:
        """Export secrets metadata (without values)."""
        data = {
            "exported_at": datetime.utcnow().isoformat(),
            "secrets": [],
        }

        for name in self.backend.list_secrets():
            secret = self.get_secret_object(name)
            if secret:
                data["secrets"].append({
                    "name": secret.name,
                    "secret_type": secret.secret_type,
                    "description": secret.description,
                    "tags": secret.tags,
                    "created_at": secret.created_at,
                    "updated_at": secret.updated_at,
                })

        with open(path, "w") as f:
            json.dump(data, f, indent=2)

        logger.info(f"Exported secrets metadata to {path}")

    def clear_cache(self) -> None:
        """Clear in-memory cache."""
        self._cache.clear()
        logger.info("Cleared secrets cache")


# Global secrets manager instance
_secrets_manager: Optional[SecretsManager] = None


def get_secrets_manager(backend: Optional[SecretsBackend] = None) -> SecretsManager:
    """Get or create global secrets manager.

    Args:
        backend: Optional custom backend

        Returns:
        SecretsManager instance
    """
    global _secrets_manager

    if _secrets_manager is None:
        if backend is None:
            # Use environment backend for production, file backend for development
            env = os.getenv("APP_ENV", "development")
            if env == "production":
                backend = EnvironmentSecretsBackend()
            else:
                backend = FileSecretsBackend(encrypt=True)

        _secrets_manager = SecretsManager(backend)

    return _secrets_manager
