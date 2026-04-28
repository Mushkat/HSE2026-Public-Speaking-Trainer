
def test_register_and_login(client):
    response = client.post("/auth/register", json={"email": "user@example.com", "password": "Password123"})
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "user@example.com"

    login_response = client.post(
        "/auth/login",
        data={"username": "user@example.com", "password": "Password123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert login_response.status_code == 200
    token_data = login_response.json()
    assert "access_token" in token_data
    assert token_data["token_type"] == "bearer"
