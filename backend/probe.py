import os
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "x" * 32)
os.environ.setdefault("ORTHANC_PASSWORD", "x")
import asyncio
from httpx import ASGITransport, AsyncClient
from app.main import app

captured = {}
from app.core import request_context as rc
_orig = rc.RequestIDMiddleware.__call__

async def spy(self, scope, receive, send):
    try:
        return await _orig(self, scope, receive, send)
    finally:
        if scope.get("type") == "http":
            r = scope.get("route")
            captured[scope.get("path")] = getattr(r, "path", None) if r else "(scope无route)"

rc.RequestIDMiddleware.__call__ = spy

async def main():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        await ac.post("/api/v1/auth/login", json={"username": "x", "password": "y"})
        await ac.get("/api/v1/encounters/abc-123/workspace")
        await ac.get("/api/v1/admin/users")
    for real, tmpl in captured.items():
        print(f"  实际={real}\n  scope['route'].path={tmpl!r}\n")

asyncio.run(main())
