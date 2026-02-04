
def register_and_login(client, email: str):
    client.post("/auth/register", json={"email": email, "password": "password123"})
    response = client.post("/auth/login", json={"email": email, "password": "password123"})
    return response.json()["access_token"]


def test_session_flow(client):
    token = register_and_login(client, "owner@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    create_response = client.post("/sessions", json={"title": "My Session"}, headers=headers)
    assert create_response.status_code == 201
    session_data = create_response.json()

    list_response = client.get("/sessions", headers=headers)
    assert list_response.status_code == 200
    list_data = list_response.json()
    assert len(list_data) == 1
    assert list_data[0]["id"] == session_data["id"]


def test_other_user_cannot_access_session(client):
    owner_token = register_and_login(client, "owner2@example.com")
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    session_response = client.post("/sessions", json={"title": "Private"}, headers=owner_headers)
    session_id = session_response.json()["id"]

    other_token = register_and_login(client, "intruder@example.com")
    other_headers = {"Authorization": f"Bearer {other_token}"}

    get_response = client.get(f"/sessions/{session_id}", headers=other_headers)
    assert get_response.status_code == 404
