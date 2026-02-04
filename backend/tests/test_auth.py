
def test_register_and_login(client):
    response = client.post("/auth/register", json={"email": "user@example.com", "password": "password123"})
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "user@example.com"

    login_response = client.post("/auth/login", json={"email": "user@example.com", "password": "password123"})
    assert login_response.status_code == 200
    token_data = login_response.json()
    assert "access_token" in token_data
    assert token_data["token_type"] == "bearer"
