"""Tests for KPI endpoints."""

import pytest
from fastapi import status


class TestKPIEndpoints:
    """Test KPI CRUD operations."""

    @pytest.fixture
    def auth_headers(self, client, test_org_data):
        """Get authentication headers."""
        response = client.post("/api/auth/register-org", json=test_org_data)
        token = response.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    @pytest.fixture
    def sample_kpi_data(self):
        """Sample KPI creation data."""
        return {
            "name": "Conversion Rate",
            "description": "Percentage of visitors who convert",
            "category": "Sales",
            "formula": "(conversions / visitors) * 100",
        }

    def test_create_kpi(self, client, auth_headers, sample_kpi_data):
        """Test creating a new KPI."""
        response = client.post(
            "/api/kpis",
            json=sample_kpi_data,
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["name"] == sample_kpi_data["name"]
        assert data["formula"] == sample_kpi_data["formula"]
        assert "id" in data

    def test_create_kpi_unauthorized(self, client, sample_kpi_data):
        """Test that unauthenticated KPI creation fails."""
        response = client.post("/api/kpis", json=sample_kpi_data)

        assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]

    def test_list_kpis(self, client, auth_headers, sample_kpi_data):
        """Test listing KPIs."""
        # Create a KPI first
        client.post("/api/kpis", json=sample_kpi_data, headers=auth_headers)

        # List KPIs
        response = client.get("/api/kpis", headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "kpis" in data
        assert "total" in data
        assert data["total"] >= 1
        assert data["kpis"][0]["name"] == sample_kpi_data["name"]

    def test_list_kpis_empty(self, client, auth_headers):
        """Test listing KPIs when none exist."""
        response = client.get("/api/kpis", headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "kpis" in data
        assert data["total"] == 0

    def test_get_kpi_by_id(self, client, auth_headers, sample_kpi_data):
        """Test getting a specific KPI."""
        # Create a KPI
        create_response = client.post(
            "/api/kpis", json=sample_kpi_data, headers=auth_headers
        )
        kpi_id = create_response.json()["id"]

        # Get the KPI
        response = client.get(f"/api/kpis/{kpi_id}", headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        # Response contains kpi and recent_entries
        data = response.json()
        assert data["kpi"]["id"] == kpi_id

    def test_get_nonexistent_kpi(self, client, auth_headers):
        """Test getting a KPI that doesn't exist."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = client.get(f"/api/kpis/{fake_id}", headers=auth_headers)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_update_kpi(self, client, auth_headers, sample_kpi_data):
        """Test updating a KPI."""
        # Create a KPI
        create_response = client.post(
            "/api/kpis", json=sample_kpi_data, headers=auth_headers
        )
        kpi_id = create_response.json()["id"]

        # Update the KPI (PUT endpoint)
        update_data = {"name": "Updated Conversion Rate"}
        response = client.put(
            f"/api/kpis/{kpi_id}",
            json=update_data,
            headers=auth_headers,
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "Updated Conversion Rate"

    def test_delete_kpi(self, client, auth_headers, sample_kpi_data):
        """Test deleting a KPI."""
        # Create a KPI
        create_response = client.post(
            "/api/kpis", json=sample_kpi_data, headers=auth_headers
        )
        kpi_id = create_response.json()["id"]

        # Delete the KPI
        response = client.delete(f"/api/kpis/{kpi_id}", headers=auth_headers)

        assert response.status_code == status.HTTP_204_NO_CONTENT

        # Verify it's gone
        get_response = client.get(f"/api/kpis/{kpi_id}", headers=auth_headers)
        assert get_response.status_code == status.HTTP_404_NOT_FOUND

    def test_seed_presets(self, client, auth_headers):
        """Test seeding preset KPIs."""
        response = client.post("/api/kpis/seed-presets", headers=auth_headers)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "presets_created" in data
        assert data["presets_created"] > 0

        # Verify KPIs were created
        list_response = client.get("/api/kpis", headers=auth_headers)
        assert list_response.json()["total"] >= data["presets_created"]
