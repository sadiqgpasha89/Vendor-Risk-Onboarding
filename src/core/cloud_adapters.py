"""Cloud Platform Adapters: Dual-stack support for Open Stack (OSS/Local) and Google Cloud Platform (GCP)."""

import os
import json
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


# =====================================================================
# 1. STORAGE ADAPTERS (Local Disk / S3 vs Google Cloud Storage)
# =====================================================================

class StorageAdapter(ABC):
    """Abstract file/blob storage interface."""

    @abstractmethod
    async def upload(self, file_bytes: bytes, destination_path: str, content_type: str = "application/octet-stream") -> str:
        """Upload raw bytes to storage, returning uri/path."""
        pass

    @abstractmethod
    async def download(self, file_path: str) -> bytes:
        """Download raw bytes from storage."""
        pass

    @abstractmethod
    async def exists(self, file_path: str) -> bool:
        """Check if file exists in storage."""
        pass

    @abstractmethod
    async def delete(self, file_path: str) -> bool:
        """Delete file from storage."""
        pass


class LocalStorageAdapter(StorageAdapter):
    """Open Stack / On-prem local filesystem storage adapter."""

    def __init__(self, base_path: str = "./data/uploads"):
        self.base_path = base_path
        try:
            os.makedirs(self.base_path, exist_ok=True)
        except (PermissionError, OSError):
            self.base_path = os.path.join(os.path.expanduser("~"), ".vendor_risk", "uploads")
            os.makedirs(self.base_path, exist_ok=True)

    def _resolve(self, path: str) -> str:
        if path.startswith(self.base_path):
            return path
        clean = path.lstrip("/")
        return os.path.join(self.base_path, clean)

    async def upload(self, file_bytes: bytes, destination_path: str, content_type: str = "application/octet-stream") -> str:
        full_path = self._resolve(destination_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "wb") as f:
            f.write(file_bytes)
        logger.info(f"[LocalStorage] Saved {len(file_bytes)} bytes to {full_path}")
        return full_path

    async def download(self, file_path: str) -> bytes:
        full_path = self._resolve(file_path)
        if not os.path.exists(full_path):
            raise FileNotFoundError(f"File not found on local storage: {full_path}")
        with open(full_path, "rb") as f:
            return f.read()

    async def exists(self, file_path: str) -> bool:
        return os.path.exists(self._resolve(file_path))

    async def delete(self, file_path: str) -> bool:
        full_path = self._resolve(file_path)
        if os.path.exists(full_path):
            os.remove(full_path)
            return True
        return False


class GCSStorageAdapter(StorageAdapter):
    """GCP Google Cloud Storage adapter."""

    def __init__(self, bucket_name: str, project_id: Optional[str] = None):
        self.bucket_name = bucket_name
        self.project_id = project_id
        self._client = None
        self._bucket = None

    def _get_bucket(self):
        if self._bucket is None:
            try:
                from google.cloud import storage
                self._client = storage.Client(project=self.project_id)
                self._bucket = self._client.bucket(self.bucket_name)
            except ImportError:
                logger.warning("google-cloud-storage not installed. Operating in fallback mock GCS mode.")
        return self._bucket

    async def upload(self, file_bytes: bytes, destination_path: str, content_type: str = "application/octet-stream") -> str:
        bucket = self._get_bucket()
        clean_path = destination_path.lstrip("/")
        if bucket:
            blob = bucket.blob(clean_path)
            blob.upload_from_string(file_bytes, content_type=content_type)
            gcs_uri = f"gs://{self.bucket_name}/{clean_path}"
            logger.info(f"[GCS] Uploaded {len(file_bytes)} bytes to {gcs_uri}")
            return gcs_uri
        # Fallback local persistence if GCP library is not installed
        local_fallback = os.path.join("/tmp/gcs_fallback", self.bucket_name, clean_path)
        os.makedirs(os.path.dirname(local_fallback), exist_ok=True)
        with open(local_fallback, "wb") as f:
            f.write(file_bytes)
        return f"gs://{self.bucket_name}/{clean_path}"

    async def download(self, file_path: str) -> bytes:
        clean_path = file_path.replace(f"gs://{self.bucket_name}/", "").lstrip("/")
        bucket = self._get_bucket()
        if bucket:
            blob = bucket.blob(clean_path)
            return blob.download_as_bytes()
        local_fallback = os.path.join("/tmp/gcs_fallback", self.bucket_name, clean_path)
        if os.path.exists(local_fallback):
            with open(local_fallback, "rb") as f:
                return f.read()
        raise FileNotFoundError(f"Blob {file_path} not found in GCS bucket {self.bucket_name}")

    async def exists(self, file_path: str) -> bool:
        clean_path = file_path.replace(f"gs://{self.bucket_name}/", "").lstrip("/")
        bucket = self._get_bucket()
        if bucket:
            return bucket.blob(clean_path).exists()
        return os.path.exists(os.path.join("/tmp/gcs_fallback", self.bucket_name, clean_path))

    async def delete(self, file_path: str) -> bool:
        clean_path = file_path.replace(f"gs://{self.bucket_name}/", "").lstrip("/")
        bucket = self._get_bucket()
        if bucket:
            blob = bucket.blob(clean_path)
            if blob.exists():
                blob.delete()
                return True
        return False


# =====================================================================
# 2. EVENT BUS ADAPTERS (Redis Streams vs Google Cloud Pub/Sub)
# =====================================================================

class EventBusAdapter(ABC):
    """Abstract messaging / event bus interface."""

    @abstractmethod
    async def publish(self, topic: str, message: Dict[str, Any], ordering_key: Optional[str] = None) -> str:
        """Publish an event to the bus."""
        pass

    @abstractmethod
    async def subscribe(self, topic_or_channel: str, handler: Any) -> None:
        """Subscribe a handler to messages on a topic."""
        pass


class RedisEventBusAdapter(EventBusAdapter):
    """Open Stack Redis Streams event bus."""

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self.redis_url = redis_url
        self._redis = None

    async def _get_client(self):
        if self._redis is None:
            try:
                import redis.asyncio as aioredis
                self._redis = aioredis.from_url(self.redis_url, decode_responses=True)
            except Exception as e:
                logger.warning(f"Could not connect to Redis: {e}. Fallback to mock.")
        return self._redis

    async def publish(self, topic: str, message: Dict[str, Any], ordering_key: Optional[str] = None) -> str:
        client = await self._get_client()
        payload = {"data": json.dumps(message), "timestamp": datetime.utcnow().isoformat()}
        if client:
            msg_id = await client.xadd(topic, payload)
            logger.info(f"[RedisStream] Published event {msg_id} to '{topic}'")
            return str(msg_id)
        logger.info(f"[MockRedisStream] Simulated publish to '{topic}': {message.get('vendor_id')}")
        return "mock-redis-msg-id"

    async def subscribe(self, topic_or_channel: str, handler: Any) -> None:
        client = await self._get_client()
        if not client:
            return
        # Basic consumer loop placeholder
        logger.info(f"[RedisStream] Subscribed handler to {topic_or_channel}")


class PubSubEventBusAdapter(EventBusAdapter):
    """GCP Google Cloud Pub/Sub event bus."""

    def __init__(self, project_id: Optional[str] = None):
        self.project_id = project_id
        self._publisher = None

    def _get_publisher(self):
        if self._publisher is None:
            try:
                from google.cloud import pubsub_v1
                self._publisher = pubsub_v1.PublisherClient()
            except ImportError:
                logger.warning("google-cloud-pubsub not installed. Operating in fallback mock Pub/Sub mode.")
        return self._publisher

    async def publish(self, topic: str, message: Dict[str, Any], ordering_key: Optional[str] = None) -> str:
        publisher = self._get_publisher()
        data_bytes = json.dumps(message).encode("utf-8")
        if publisher and self.project_id:
            topic_path = publisher.topic_path(self.project_id, topic)
            kwargs = {}
            if ordering_key:
                kwargs["ordering_key"] = ordering_key
            future = publisher.publish(topic_path, data=data_bytes, **kwargs)
            message_id = future.result()
            logger.info(f"[GCP PubSub] Published message {message_id} to {topic_path}")
            return str(message_id)
        logger.info(f"[MockGCPPubSub] Simulated publish to '{topic}': {message.get('vendor_id')}")
        return "mock-pubsub-msg-id"

    async def subscribe(self, topic_or_channel: str, handler: Any) -> None:
        logger.info(f"[GCP PubSub] Subscribed handler to {topic_or_channel}")


# =====================================================================
# 3. FACTORY DISPATCHERS
# =====================================================================

def get_storage_adapter() -> StorageAdapter:
    """Instantiate the active storage adapter based on settings."""
    from src.config.settings import settings
    provider = getattr(settings, "cloud_provider", "open_stack")
    if provider == "gcp" or getattr(settings, "file_storage_type", "local") == "gcs":
        return GCSStorageAdapter(
            bucket_name=settings.gcp.gcs_bucket,
            project_id=settings.gcp.project_id,
        )
    return LocalStorageAdapter(base_path=settings.file_storage_path)


def get_event_bus_adapter() -> EventBusAdapter:
    """Instantiate the active messaging adapter based on settings."""
    from src.config.settings import settings
    provider = getattr(settings, "cloud_provider", "open_stack")
    if provider == "gcp":
        return PubSubEventBusAdapter(project_id=settings.gcp.project_id)
    return RedisEventBusAdapter(redis_url=settings.redis.url)
