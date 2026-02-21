"""Testes para o banco de dados."""

import os
import tempfile

import pytest

from ratonet.dashboard.db import (
    approve_streamer,
    create_streamer,
    delete_streamer,
    get_streamer_by_api_key,
    get_streamer_by_email,
    get_streamer_by_id,
    get_streamer_by_pull_key,
    init_db,
    list_streamers,
    update_streamer,
)


@pytest.fixture
async def db_path():
    """Cria banco temporário para testes."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    await init_db(path)
    yield path
    os.unlink(path)


@pytest.mark.asyncio
async def test_init_db(db_path):
    """Banco inicializa sem erro."""
    assert os.path.exists(db_path)


@pytest.mark.asyncio
async def test_create_and_get_streamer(db_path):
    """Cria streamer e busca por ID."""
    result = await create_streamer(
        name="Test", email="test@test.com", db_path=db_path,
    )
    assert result["name"] == "Test"
    assert result["api_key"].startswith("rn_")
    assert result["pull_key"].startswith("pk_")

    streamer = await get_streamer_by_id(result["id"], db_path=db_path)
    assert streamer is not None
    assert streamer["name"] == "Test"


@pytest.mark.asyncio
async def test_get_by_api_key(db_path):
    """Busca streamer por API key."""
    result = await create_streamer(
        name="KeyTest", email="key@test.com", db_path=db_path,
    )
    found = await get_streamer_by_api_key(result["api_key"], db_path=db_path)
    assert found is not None
    assert found["id"] == result["id"]


@pytest.mark.asyncio
async def test_get_by_pull_key(db_path):
    """Busca streamer por pull key."""
    result = await create_streamer(
        name="PullTest", email="pull@test.com", db_path=db_path,
    )
    found = await get_streamer_by_pull_key(result["pull_key"], db_path=db_path)
    assert found is not None
    assert found["id"] == result["id"]


@pytest.mark.asyncio
async def test_get_by_email(db_path):
    """Busca streamer por email."""
    await create_streamer(name="EmailTest", email="find@test.com", db_path=db_path)
    found = await get_streamer_by_email("find@test.com", db_path=db_path)
    assert found is not None
    assert found["name"] == "EmailTest"


@pytest.mark.asyncio
async def test_list_streamers(db_path):
    """Lista streamers com filtro de aprovação."""
    await create_streamer(name="A", email="a@test.com", db_path=db_path)
    await create_streamer(
        name="B", email="b@test.com", auto_approve=True, db_path=db_path,
    )

    all_streamers = await list_streamers(db_path=db_path)
    assert len(all_streamers) == 2

    approved = await list_streamers(approved_only=True, db_path=db_path)
    assert len(approved) == 1
    assert approved[0]["name"] == "B"


@pytest.mark.asyncio
async def test_update_streamer(db_path):
    """Atualiza campos do streamer."""
    result = await create_streamer(
        name="Update", email="update@test.com", db_path=db_path,
    )
    success = await update_streamer(
        result["id"], db_path=db_path, name="Updated Name", color="#00ff00",
    )
    assert success is True

    updated = await get_streamer_by_id(result["id"], db_path=db_path)
    assert updated["name"] == "Updated Name"
    assert updated["color"] == "#00ff00"


@pytest.mark.asyncio
async def test_approve_streamer(db_path):
    """Aprova streamer."""
    result = await create_streamer(
        name="Approve", email="approve@test.com", db_path=db_path,
    )
    assert result["approved"] is False

    await approve_streamer(result["id"], db_path=db_path)
    streamer = await get_streamer_by_id(result["id"], db_path=db_path)
    assert streamer["approved"] is True


@pytest.mark.asyncio
async def test_delete_streamer(db_path):
    """Remove streamer."""
    result = await create_streamer(
        name="Delete", email="delete@test.com", db_path=db_path,
    )
    deleted = await delete_streamer(result["id"], db_path=db_path)
    assert deleted is True

    found = await get_streamer_by_id(result["id"], db_path=db_path)
    assert found is None
