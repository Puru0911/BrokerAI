from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import settings
from app.db import init_db as init_db_mod


@pytest.mark.asyncio
async def test_local_init_uses_create_all_and_never_drops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ENV", "local")
    connection = MagicMock()
    connection.run_sync = AsyncMock()
    connection.execute = AsyncMock()
    begin = MagicMock()
    begin.__aenter__ = AsyncMock(return_value=connection)
    begin.__aexit__ = AsyncMock(return_value=None)

    with patch.object(init_db_mod, "engine") as engine:
        engine.begin.return_value = begin
        await init_db_mod.init_db()

    connection.run_sync.assert_awaited()
    sql = str(connection.execute.await_args.args[0])
    assert "DROP TABLE" not in sql
    assert "notebook" in sql


@pytest.mark.asyncio
async def test_production_init_fails_without_alembic_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ENV", "production")
    connection = MagicMock()
    connection.run_sync = AsyncMock(return_value=None)
    connect = MagicMock()
    connect.__aenter__ = AsyncMock(return_value=connection)
    connect.__aexit__ = AsyncMock(return_value=None)

    with (
        patch.object(init_db_mod, "engine") as engine,
        patch.object(init_db_mod, "alembic_head_revision", return_value="0001_initial"),
    ):
        engine.connect.return_value = connect
        with pytest.raises(RuntimeError, match="no Alembic revision"):
            await init_db_mod.init_db()


@pytest.mark.asyncio
async def test_production_init_fails_when_schema_is_behind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ENV", "production")
    connection = MagicMock()
    connection.run_sync = AsyncMock(return_value="0001_initial")
    connect = MagicMock()
    connect.__aenter__ = AsyncMock(return_value=connection)
    connect.__aexit__ = AsyncMock(return_value=None)

    with (
        patch.object(init_db_mod, "engine") as engine,
        patch.object(init_db_mod, "alembic_head_revision", return_value="0002_later"),
    ):
        engine.connect.return_value = connect
        with pytest.raises(RuntimeError, match="behind"):
            await init_db_mod.init_db()


def test_supabase_pooler_ssl_encrypts_without_verify_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ssl

    from app.db.session import connect_args, database_ssl_context

    monkeypatch.setattr(
        settings,
        "DATABASE_URL",
        "postgresql+asyncpg://postgres.abc:pass@aws-1-ap-northeast-1.pooler.supabase.com:6543/postgres",
    )
    monkeypatch.setattr(settings, "DATABASE_SSL_VERIFY", False)
    context = database_ssl_context()
    assert context is not None
    assert context.verify_mode == ssl.CERT_NONE
    assert connect_args()["ssl"].verify_mode == ssl.CERT_NONE


def test_local_postgres_does_not_force_ssl(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.db.session import connect_args, database_ssl_context

    monkeypatch.setattr(
        settings,
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/brokerai",
    )
    assert database_ssl_context() is None
    assert "ssl" not in connect_args()
