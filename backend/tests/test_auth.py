from datetime import UTC, datetime, timedelta

import jwt
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User


async def test_login_returns_token_and_profile(client: AsyncClient, create_user) -> None:
    await create_user(email="admin@example.com", password="password123", role="admin")

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "password123"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["email"] == "admin@example.com"
    assert body["user"]["role"] == "admin"
    assert "hashed_password" not in body["user"]
    assert response.cookies.get("access_token") == body["access_token"]


async def test_login_normalizes_email(client: AsyncClient, create_user) -> None:
    await create_user(email="admin@example.com", password="password123")

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "ADMIN@EXAMPLE.COM", "password": "password123"},
    )

    assert response.status_code == 200


async def test_login_rejects_bad_password(client: AsyncClient, create_user) -> None:
    await create_user(email="admin@example.com", password="password123")

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "wrong-password"},
    )

    assert response.status_code == 401


async def test_login_rejects_unknown_email(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "missing@example.com", "password": "password123"},
    )

    assert response.status_code == 401


async def test_login_validation_hides_the_submitted_value(client: AsyncClient) -> None:
    password = "secret-login-password"

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "not-an-email", "password": password},
    )

    assert response.status_code == 422
    assert password not in response.text
    assert "not-an-email" not in response.text
    assert all("input" not in error and "ctx" not in error for error in response.json()["detail"])


async def test_login_rejects_inactive_user(client: AsyncClient, create_user) -> None:
    await create_user(
        email="inactive@example.com",
        password="password123",
        is_active=False,
    )

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "inactive@example.com", "password": "password123"},
    )

    assert response.status_code == 401


async def test_me_accepts_cookie(client: AsyncClient, create_user, login) -> None:
    await create_user(email="admin@example.com", password="password123")
    await login("admin@example.com", "password123")

    response = await client.get("/api/v1/auth/me")

    assert response.status_code == 200
    assert response.json()["email"] == "admin@example.com"


async def test_me_accepts_bearer_token(client: AsyncClient, create_user, login) -> None:
    await create_user(email="admin@example.com", password="password123")
    token = await login("admin@example.com", "password123")
    client.cookies.clear()

    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200


async def test_me_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me")

    assert response.status_code == 401


async def test_me_rejects_invalid_token(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer not-a-token"},
    )

    assert response.status_code == 401


async def test_me_rejects_token_for_deactivated_user(
    client: AsyncClient,
    create_user,
    login,
    db_session: AsyncSession,
) -> None:
    user = await create_user(email="viewer@example.com", password="password123")
    token = await login("viewer@example.com", "password123")

    await db_session.execute(update(User).where(User.id == user.id).values(is_active=False))
    await db_session.commit()

    client.cookies.clear()
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


async def test_logout_clears_cookie(client: AsyncClient, create_user, login) -> None:
    await create_user(email="admin@example.com", password="password123")
    await login("admin@example.com", "password123")

    logout_response = await client.post("/api/v1/auth/logout")
    me_response = await client.get("/api/v1/auth/me")

    assert logout_response.status_code == 204
    assert me_response.status_code == 401


async def test_login_rejects_malformed_stored_hash(
    client: AsyncClient,
    create_user,
    db_session: AsyncSession,
) -> None:
    user = await create_user(email="broken@example.com", password="password123")
    await db_session.execute(
        update(User).where(User.id == user.id).values(hashed_password="not-a-valid-hash")
    )
    await db_session.commit()

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "broken@example.com", "password": "password123"},
    )

    assert response.status_code == 401


async def test_me_rejects_expired_token(
    client: AsyncClient,
    create_user,
    test_settings,
) -> None:
    user = await create_user(email="expired@example.com")
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(user.id),
            "iat": now - timedelta(hours=2),
            "exp": now - timedelta(hours=1),
            "ver": 0,
        },
        test_settings.jwt_secret,
        algorithm=test_settings.jwt_algorithm,
    )

    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


async def test_me_rejects_token_missing_required_claim(
    client: AsyncClient,
    create_user,
    test_settings,
) -> None:
    user = await create_user(email="claims@example.com")
    now = datetime.now(UTC)
    payload = {
        "sub": str(user.id),
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "ver": 0,
    }
    payload.pop("exp")
    token = jwt.encode(
        payload,
        test_settings.jwt_secret,
        algorithm=test_settings.jwt_algorithm,
    )

    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


async def test_me_rejects_token_signed_with_another_algorithm(
    client: AsyncClient,
    create_user,
    test_settings,
) -> None:
    user = await create_user(email="algorithm@example.com")
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(user.id),
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "ver": 0,
        },
        test_settings.jwt_secret,
        algorithm="HS512",
    )

    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


async def test_me_rejects_stale_token_version(
    client: AsyncClient,
    create_user,
    login,
    db_session: AsyncSession,
) -> None:
    user = await create_user(email="stale@example.com", password="password123")
    token = await login("stale@example.com", "password123")

    await db_session.execute(update(User).where(User.id == user.id).values(token_version=1))
    await db_session.commit()
    client.cookies.clear()

    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


async def test_bearer_takes_precedence_over_cookie(
    client: AsyncClient,
    create_user,
    login,
) -> None:
    await create_user(
        email="admin@example.com",
        password="admin-password",
        role="admin",
    )
    await create_user(email="viewer@example.com", password="viewer-password")
    admin_token = await login("admin@example.com", "admin-password")
    await login("viewer@example.com", "viewer-password")

    admin_response = await client.get(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    invalid_bearer_response = await client.get(
        "/api/v1/users",
        headers={"Authorization": "Bearer not-a-token"},
    )

    assert admin_response.status_code == 200
    assert invalid_bearer_response.status_code == 401


async def test_logout_does_not_revoke_bearer_token(
    client: AsyncClient,
    create_user,
    login,
) -> None:
    await create_user(email="logout@example.com", password="password123")
    token = await login("logout@example.com", "password123")

    logout_response = await client.post("/api/v1/auth/logout")
    client.cookies.clear()
    me_response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert logout_response.status_code == 204
    assert me_response.status_code == 200
