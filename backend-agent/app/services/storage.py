from __future__ import annotations

from typing import Protocol
from urllib.parse import quote

import httpx

from app.core.config import settings


class StorageNotConfiguredError(RuntimeError):
    """Raised when file storage cannot be reached."""


class AttachmentStore(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...

    async def fetch(self, key: str) -> tuple[bytes, str]: ...

    async def sign(self, key: str, expires_in: int = 3600) -> str: ...

    async def delete(self, key: str) -> None: ...


class MemoryAttachmentStore:
    """In-process store for tests. Not used in production."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = (data, content_type)

    async def fetch(self, key: str) -> tuple[bytes, str]:
        if key not in self.objects:
            raise FileNotFoundError(key)
        data, content_type = self.objects[key]
        return data, content_type

    async def sign(self, key: str, expires_in: int = 3600) -> str:
        if key not in self.objects:
            raise FileNotFoundError(key)
        return f"memory://{key}?ttl={expires_in}"

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)


class SupabaseAttachmentStore:
    """Private Supabase Storage bucket, accessed with the service role."""

    def __init__(self) -> None:
        if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
            raise StorageNotConfiguredError(
                "Supabase Storage is not configured. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY."
            )
        self.base_url = settings.SUPABASE_URL.rstrip("/")
        self.bucket = settings.SUPABASE_STORAGE_BUCKET
        self._headers = {
            "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
            "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        }
        self._bucket_ready = False

    async def _ensure_bucket(self, client: httpx.AsyncClient) -> None:
        if self._bucket_ready:
            return
        response = await client.post(
            f"{self.base_url}/storage/v1/bucket",
            headers={**self._headers, "Content-Type": "application/json"},
            json={
                "id": self.bucket,
                "name": self.bucket,
                "public": False,
                "fileSizeLimit": settings.ATTACHMENT_MAX_BYTES,
            },
        )
        if response.status_code not in {200, 201, 409}:
            detail = response.text
            if "already exists" not in detail.lower() and "duplicate" not in detail.lower():
                raise StorageNotConfiguredError(
                    f"Could not create storage bucket '{self.bucket}': {response.status_code} {detail}"
                )
        self._bucket_ready = True

    def _object_url(self, key: str, *, authenticated: bool = False) -> str:
        encoded = quote(key, safe="/")
        kind = "object/authenticated" if authenticated else "object"
        return f"{self.base_url}/storage/v1/{kind}/{self.bucket}/{encoded}"

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        async with httpx.AsyncClient(timeout=60.0) as client:
            await self._ensure_bucket(client)
            response = await client.post(
                self._object_url(key),
                headers={
                    **self._headers,
                    "Content-Type": content_type or "application/octet-stream",
                    "x-upsert": "true",
                },
                content=data,
            )
            if response.status_code not in {200, 201}:
                raise StorageNotConfiguredError(
                    f"Upload failed ({response.status_code}): {response.text}"
                )

    async def fetch(self, key: str) -> tuple[bytes, str]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            for authenticated in (True, False):
                response = await client.get(
                    self._object_url(key, authenticated=authenticated),
                    headers=self._headers,
                )
                if response.status_code == 200:
                    content_type = response.headers.get("content-type") or "application/octet-stream"
                    return response.content, content_type.split(";")[0].strip()
            raise FileNotFoundError(key)

    async def sign(self, key: str, expires_in: int = 3600) -> str:
        async with httpx.AsyncClient(timeout=20.0) as client:
            encoded = quote(key, safe="/")
            response = await client.post(
                f"{self.base_url}/storage/v1/object/sign/{self.bucket}/{encoded}",
                headers={**self._headers, "Content-Type": "application/json"},
                json={"expiresIn": expires_in},
            )
            if response.status_code != 200:
                raise FileNotFoundError(key)
            payload = response.json()
            signed = payload.get("signedURL") or payload.get("signedUrl") or ""
            if not signed:
                raise FileNotFoundError(key)
            if signed.startswith("http"):
                return signed
            path = signed if signed.startswith("/") else f"/{signed}"
            if path.startswith("/storage/v1/"):
                return f"{self.base_url}{path}"
            if path.startswith("/object/"):
                return f"{self.base_url}/storage/v1{path}"
            return f"{self.base_url}/storage/v1{path}"

    async def delete(self, key: str) -> None:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.request(
                "DELETE",
                f"{self.base_url}/storage/v1/object/{self.bucket}",
                headers={**self._headers, "Content-Type": "application/json"},
                json={"prefixes": [key]},
            )
            if response.status_code not in {200, 400, 404}:
                raise StorageNotConfiguredError(
                    f"Delete failed ({response.status_code}): {response.text}"
                )


_store: AttachmentStore | None = None


def get_attachment_store() -> AttachmentStore:
    global _store
    if _store is None:
        _store = SupabaseAttachmentStore()
    return _store


def set_attachment_store(store: AttachmentStore | None) -> None:
    global _store
    _store = store
