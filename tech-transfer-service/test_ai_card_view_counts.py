from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.middleware import identity
from modules.ai import service
from routes import ai


def test_card_counts_are_batched_read_only_and_exclude_non_public_content():
    cursor = MagicMock()
    cursor.fetchall.side_effect = [
        [{"id": 7, "view_count": 12}],
        [{"id": 8, "view_count": 3}],
    ]
    commits = []

    @contextmanager
    def read_cursor(commit=False):
        commits.append(commit)
        yield cursor

    cards = [
        {"card_type": "achievement", "id": 7},
        {"card_type": "achievement", "id": 7},
        {"card_type": "achievement", "id": 9},
        {"card_type": "demand", "id": 8},
    ]
    with patch.object(service, "get_cursor", read_cursor):
        result = service.get_card_view_counts(cards)

    assert result == [
        {"card_type": "achievement", "id": 7, "viewCount": 12},
        {"card_type": "demand", "id": 8, "viewCount": 3},
    ]
    assert commits == [False]
    assert cursor.execute.call_count == 2
    for statement in cursor.execute.call_args_list:
        sql = statement.args[0].lower()
        assert sql.strip().startswith("select")
        assert "status = 'published'" in sql
        assert "deleted_at is null" in sql


def test_card_count_endpoint_validates_batch_and_returns_live_counts():
    app = FastAPI()
    app.include_router(ai.router)
    app.dependency_overrides[identity] = lambda: {"userId": 7}
    app.dependency_overrides[ai.require_ai_enabled] = lambda: None
    with TestClient(app) as client:
        with patch.object(ai, "get_card_view_counts", create=True, return_value=[
            {"card_type": "achievement", "id": 7, "viewCount": 12},
        ]):
            response = client.post("/api/tech-transfer/v1/ai/cards/view-counts", json={
                "cards": [{"card_type": "achievement", "id": 7}],
            })
        assert response.status_code == 200
        assert response.json()["data"]["list"][0]["viewCount"] == 12
        for cards in [
            [{"card_type": "user", "id": 7}],
            [{"card_type": "achievement", "id": -1}],
            [{"card_type": "demand", "id": 7}] * 51,
        ]:
            response = client.post("/api/tech-transfer/v1/ai/cards/view-counts", json={"cards": cards})
            assert response.status_code == 422
