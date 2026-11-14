import asyncio
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.models import User


@pytest.fixture
async def admin(create_user):
    return await create_user(
        email="admin@example.com",
        password="admin-password",
        role="admin",
    )


@pytest.fixture
async def viewer(create_user):
    return await create_user(
        email="viewer@example.com",
        password="viewer-password",
        role="viewer",
    )


async def test_list_users_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/users")

    assert response.status_code == 401


async def test_viewer_cannot_list_users(
    client: AsyncClient,
    viewer,
    login,
) -> None:
    await login(viewer.email, "viewer-password")

    response = await client.get("/api/v1/users")

    assert response.status_code == 403


async def test_admin_lists_users(
    client: AsyncClient,
    admin,
    viewer,
    login,
) -> None:
    await login(admin.email, "admin-password")

    response = await client.get("/api/v1/users")

    assert response.status_code == 200
    body = response.json()
    assert {user["email"] for user in body} == {
        "admin@example.com",
        "viewer@example.com",
    }
    assert all("hashed_password" not in user for user in body)


async def test_admin_creates_user(client: AsyncClient, admin, login) -> None:
    await login(admin.email, "admin-password")

    response = await client.post(
        "/api/v1/users",
        json={
            "email": "new@example.com",
            "full_name": "New User",
            "password": "new-password",
            "role": "viewer",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new@example.com"
    assert body["role"] == "viewer"
    assert "hashed_password" not in body

    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": "new@example.com", "password": "new-password"},
    )
    assert login_response.status_code == 200


async def test_viewer_cannot_create_user(
    client: AsyncClient,
    viewer,
    login,
) -> None:
    await login(viewer.email, "viewer-password")

    response = await client.post(
        "/api/v1/users",
        json={
            "email": "new@example.com",
            "full_name": "New User",
            "password": "new-password",
        },
    )

    assert response.status_code == 403


async def test_duplicate_email_returns_conflict(
    client: AsyncClient,
    admin,
    login,
) -> None:
    await login(admin.email, "admin-password")
    payload = {
        "email": "duplicate@example.com",
        "full_name": "Duplicate User",
        "password": "new-password",
    }

    first = await client.post("/api/v1/users", json=payload)
    second = await client.post("/api/v1/users", json=payload)

    assert first.status_code == 201
    assert second.status_code == 409


async def test_admin_updates_role_and_name(
    client: AsyncClient,
    admin,
    viewer,
    login,
) -> None:
    await login(admin.email, "admin-password")

    response = await client.patch(
        f"/api/v1/users/{viewer.id}",
        json={"role": "admin", "full_name": "Promoted Viewer"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "admin"
    assert body["full_name"] == "Promoted Viewer"


async def test_viewer_cannot_update_user(
    client: AsyncClient,
    admin,
    viewer,
    login,
) -> None:
    await login(viewer.email, "viewer-password")

    response = await client.patch(
        f"/api/v1/users/{admin.id}",
        json={"role": "viewer"},
    )

    assert response.status_code == 403


async def test_patch_unknown_user_returns_not_found(
    client: AsyncClient,
    admin,
    login,
) -> None:
    await login(admin.email, "admin-password")

    response = await client.patch(
        f"/api/v1/users/{uuid4()}",
        json={"full_name": "Nobody"},
    )

    assert response.status_code == 404


async def test_patch_rejects_email_change(
    client: AsyncClient,
    admin,
    viewer,
    login,
) -> None:
    await login(admin.email, "admin-password")

    response = await client.patch(
        f"/api/v1/users/{viewer.id}",
        json={"email": "changed@example.com"},
    )

    assert response.status_code == 422


async def test_create_rejects_short_password(
    client: AsyncClient,
    admin,
    login,
) -> None:
    await login(admin.email, "admin-password")

    response = await client.post(
        "/api/v1/users",
        json={
            "email": "short@example.com",
            "full_name": "Short Password",
            "password": "short",
        },
    )

    assert response.status_code == 422


async def test_create_rejects_password_over_bcrypt_bytes(
    client: AsyncClient,
    admin,
    login,
) -> None:
    await login(admin.email, "admin-password")

    response = await client.post(
        "/api/v1/users",
        json={
            "email": "long@example.com",
            "full_name": "Long Password",
            "password": "é" * 40,
        },
    )

    assert response.status_code == 422


async def test_password_reset_takes_effect(
    client: AsyncClient,
    admin,
    viewer,
    login,
) -> None:
    await login(admin.email, "admin-password")

    reset_response = await client.patch(
        f"/api/v1/users/{viewer.id}",
        json={"password": "updated-password"},
    )
    old_login = await client.post(
        "/api/v1/auth/login",
        json={"email": viewer.email, "password": "viewer-password"},
    )
    new_login = await client.post(
        "/api/v1/auth/login",
        json={"email": viewer.email, "password": "updated-password"},
    )

    assert reset_response.status_code == 200
    assert old_login.status_code == 401
    assert new_login.status_code == 200


async def test_last_admin_cannot_be_demoted(
    client: AsyncClient,
    admin,
    login,
) -> None:
    await login(admin.email, "admin-password")

    response = await client.patch(
        f"/api/v1/users/{admin.id}",
        json={"role": "viewer"},
    )

    assert response.status_code == 403


async def test_last_admin_cannot_be_deactivated(
    client: AsyncClient,
    admin,
    login,
) -> None:
    await login(admin.email, "admin-password")

    response = await client.patch(
        f"/api/v1/users/{admin.id}",
        json={"is_active": False},
    )

    assert response.status_code == 403


async def test_inactive_admin_does_not_satisfy_guard(
    client: AsyncClient,
    admin,
    create_user,
    login,
) -> None:
    await create_user(
        email="inactive-admin@example.com",
        password="inactive-password",
        role="admin",
        is_active=False,
    )
    await login(admin.email, "admin-password")

    response = await client.patch(
        f"/api/v1/users/{admin.id}",
        json={"role": "viewer"},
    )

    assert response.status_code == 403


async def test_second_active_admin_can_demote_first(
    client: AsyncClient,
    create_user,
    login,
) -> None:
    first_admin = await create_user(
        email="first-admin@example.com",
        password="first-password",
        role="admin",
    )
    await create_user(
        email="second-admin@example.com",
        password="second-password",
        role="admin",
    )
    await login("second-admin@example.com", "second-password")

    response = await client.patch(
        f"/api/v1/users/{first_admin.id}",
        json={"role": "viewer"},
    )

    assert response.status_code == 200
    assert response.json()["role"] == "viewer"


async def test_create_rejects_case_variant_duplicate_email(
    client: AsyncClient,
    admin,
    login,
) -> None:
    await login(admin.email, "admin-password")
    payload = {
        "full_name": "Case User",
        "password": "case-password",
    }

    first = await client.post(
        "/api/v1/users",
        json={"email": "CaseUser@Example.com", **payload},
    )
    second = await client.post(
        "/api/v1/users",
        json={"email": "caseuser@example.com", **payload},
    )

    assert first.status_code == 201
    assert second.status_code == 409


async def test_password_reset_revokes_existing_tokens(
    client: AsyncClient,
    admin,
    viewer,
    login,
) -> None:
    viewer_token = await login(viewer.email, "viewer-password")
    admin_token = await login(admin.email, "admin-password")
    client.cookies.clear()

    reset_response = await client.patch(
        f"/api/v1/users/{viewer.id}",
        json={"password": "updated-password"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    stale_response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    new_login = await client.post(
        "/api/v1/auth/login",
        json={"email": viewer.email, "password": "updated-password"},
    )

    assert reset_response.status_code == 200
    assert stale_response.status_code == 401
    assert new_login.status_code == 200


async def test_concurrent_patch_cannot_remove_last_admin(
    client: AsyncClient,
    create_user,
    login,
    db_session,
) -> None:
    first = await create_user(
        email="first-admin@example.com",
        password="first-password",
        role="admin",
    )
    second = await create_user(
        email="second-admin@example.com",
        password="second-password",
        role="admin",
    )
    await login("first-admin@example.com", "first-password")

    responses = await asyncio.gather(
        client.patch(f"/api/v1/users/{first.id}", json={"role": "viewer"}),
        client.patch(f"/api/v1/users/{second.id}", json={"role": "viewer"}),
    )

    statuses = sorted(response.status_code for response in responses)
    active_admins = (
        await db_session.scalars(select(User).where(User.role == "admin", User.is_active.is_(True)))
    ).all()

    assert statuses == [200, 403]
    assert len(active_admins) == 1
