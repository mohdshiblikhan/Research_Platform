def test_ping(client):
    """
    Test the basic FastAPI app initialization and test client setup.
    We assume there's a simple health check or we can just test 404 for a non-existent route.
    """
    response = client.get("/non-existent-route")
    assert response.status_code == 404
