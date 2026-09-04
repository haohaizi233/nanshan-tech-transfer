"""真实浏览量：详情访问应原子累加，测试结束后还原计数。"""
import psycopg2
import requests

BASE = "http://127.0.0.1:8787/api/tech-transfer/v1"
DB = dict(host="127.0.0.1", port=5432, user="postgres", password="postgres123", dbname="tech_transfer")


def reset_counts():
    conn = psycopg2.connect(**DB)
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE demand SET view_count=0")
            cur.execute("UPDATE achievement SET view_count=0")
        conn.commit()
    finally:
        conn.close()


def bootstrap():
    response = requests.post(
        f"{BASE}/auth/bootstrap", json={"hostCredential": "local-dev-ticket-view-counter"}, timeout=10
    )
    return {"Authorization": "Bearer " + response.json()["data"]["accessToken"]}


def first_published(path, headers):
    response = requests.get(f"{BASE}/{path}?page=1&pageSize=1", headers=headers, timeout=10)
    assert response.status_code == 200, response.text
    return response.json()["data"]["list"][0]["id"]


def detail(path, item_id, headers):
    response = requests.get(f"{BASE}/{path}/{item_id}", headers=headers, timeout=10)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def main():
    reset_counts()
    try:
        headers = bootstrap()
        checks = (("demands", "需求"), ("achievements", "成果"))
        for path, label in checks:
            item_id = first_published(path, headers)
            first = detail(path, item_id, headers)
            second = detail(path, item_id, headers)
            assert first["viewCount"] == 1, f"{label}首次浏览应为 1，实际 {first['viewCount']}"
            assert second["viewCount"] == 2, f"{label}第二次浏览应为 2，实际 {second['viewCount']}"
            print(f"[PASS] {label}详情浏览量按访问次数累计：1 → 2")
    finally:
        reset_counts()


if __name__ == "__main__":
    main()
