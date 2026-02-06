"""Tests for authentication endpoints."""

import pytest
from fastapi import status


class TestAuthEndpoints:
    """Test authentication flow."""

    def test_register_organization(self, client, test_org_data):
        """Test organization registration."""
        response = client.post("/api/auth/register-org", json=test_org_data)

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert "user" in data
        assert data["user"]["email"] == test_org_data["admin_email"]
        assert data["user"]["role_label"] == "Admin"
        assert "organization" in data
        assert data["organization"]["name"] == test_org_data["org_name"]

    def test_register_duplicate_email(self, client, test_org_data):
        """Test that duplicate email registration fails."""
        # Register first time
        client.post("/api/auth/register-org", json=test_org_data)

        # Try to register again with same email
        response = client.post("/api/auth/register-org", json=test_org_data)

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_login_success(self, client, test_org_data):
        """Test successful login."""
        # Register first
        client.post("/api/auth/register-org", json=test_org_data)

        # Login with JSON body
        response = client.post(
            "/api/auth/login",
            json={
                "email": test_org_data["admin_email"],
                "password": test_org_data["admin_password"],
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    def test_login_invalid_credentials(self, client, test_org_data):
        """Test login with wrong password."""
        # Register first
        client.post("/api/auth/register-org", json=test_org_data)

        # Try login with wrong password
        response = client.post(
            "/api/auth/login",
            json={
                "email": test_org_data["admin_email"],
                "password": "wrongpassword",
            },
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_login_nonexistent_user(self, client):
        """Test login for user that doesn't exist."""
        response = client.post(
            "/api/auth/login",
            json={"email": "nobody@test.com", "password": "password"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_get_current_user(self, client, test_org_data):
        """Test getting current user info."""
        # Register and get token
        register_response = client.post("/api/auth/register-org", json=test_org_data)
        token = register_response.json()["access_token"]

        # Get current user
        response = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["email"] == test_org_data["admin_email"]
        assert data["name"] == test_org_data["admin_name"]
        assert "organization" in data

    def test_get_current_user_no_token(self, client):
        """Test that unauthenticated request fails."""
        response = client.get("/api/auth/me")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_get_current_user_invalid_token(self, client):
        """Test that invalid token fails."""
        response = client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer invalid_token"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_refresh_token(self, client, test_org_data):
        """Test token refresh flow."""
        # Register and get tokens
        register_response = client.post("/api/auth/register-org", json=test_org_data)
        refresh_token = register_response.json()["refresh_token"]

        # Refresh the token
        response = client.post(
            "/api/auth/refresh",
            json={"refresh_token": refresh_token},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
