"""Real PostgreSQL query regression tests; fixtures live only in temporary tables."""

import os
from contextlib import contextmanager
from unittest.mock import patch

import psycopg2
import pytest
from psycopg2.extras import RealDictCursor

from core.errors import BizError
from modules.membership import service


@pytest.fixture
def members_db():
    conn = psycopg2.connect(
        os.environ.get("MEMBER_TEST_DSN", "host=127.0.0.1 user=postgres dbname=postgres"), cursor_factory=RealDictCursor
    )
    cur = conn.cursor()
    cur.execute("""
        CREATE TEMP TABLE app_user(id bigint, user_no text);
        CREATE TEMP TABLE institution(id bigint, name text);
        CREATE TEMP TABLE user_profile(user_id bigint PRIMARY KEY, display_name text);
        CREATE TEMP TABLE user_role(user_id bigint, role_code text);
        CREATE TEMP TABLE organization_membership(id bigint, user_id bigint, org_id bigint, role text, status text, version int, department text, title text);
        CREATE TEMP TABLE organization_membership_application(id bigint, user_id bigint, org_id bigint, status text, real_name text, reviewed_at timestamptz);
        CREATE TEMP TABLE organization_admin_application(LIKE organization_membership_application);
        INSERT INTO app_user SELECT n, 'U20260000' || n FROM generate_series(1,8) n;
        INSERT INTO institution VALUES (10,'A'),(20,'B');
        INSERT INTO organization_membership SELECT n,n,10,CASE WHEN n=1 THEN 'admin' ELSE 'member' END,'active',3,NULL,NULL FROM generate_series(1,8) n;
        INSERT INTO organization_membership VALUES (99,2,20,'member','active',4,NULL,NULL);
        INSERT INTO user_profile VALUES (3,'林青'),(4,'13800138000'),(5,'U202600005'),(6,'  '),(7,'测试用户'),(8,'Alice Smith');
        INSERT INTO organization_membership_application VALUES
        (1,2,10,'approved','  李明  ','2026-01-01'),
        (2,2,20,'approved','另一机构姓名','2026-11-01'),
        (3,2,10,'pending','未批准姓名','2026-12-01'),
        (4,2,10,'approved','旧姓名','2025-01-01'),
        (5,2,10,'approved','  ','2026-12-01');
        INSERT INTO organization_admin_application VALUES (1,1,10,'approved','管理员姓名','2026-01-01');
    """)

    @contextmanager
    def cursor():
        yield cur

    try:
        with patch.object(service, "get_cursor", cursor):
            yield cur
    finally:
        conn.rollback()
        conn.close()


def test_names_and_pagination(members_db):
    result = service.list_org_members({"userId": 1}, 10, "active", 1, 50)
    assert result["total"] == 8
    rows = result["list"]
    assert [r.get("realName") for r in rows] == ["管理员姓名", "李明", "林青", None, None, None, None, "Alice Smith"]
    assert rows[1]["nameSource"] == "membership_application"
    assert rows[2]["nameSource"] == "profile_display_name"
    assert rows[1]["id"] == 2 and rows[1]["version"] == 3 and rows[1]["userNo"] == "U202600002"
    page = service.list_org_members({"userId": 1}, 10, "active", 2, 3)
    assert page["total"] == 8 and [r["id"] for r in page["list"]] == [4, 5, 6]


def test_newer_review_wins_across_tables(members_db):
    members_db.execute("INSERT INTO organization_admin_application VALUES (9,2,10,'approved','更新姓名','2026-02-01')")
    row = service.list_org_members({"userId": 1}, 10, "active", 1, 50)["list"][1]
    assert row.get("realName") == "更新姓名"
    members_db.execute(
        "INSERT INTO organization_membership_application VALUES (10,2,10,'approved','最新成员姓名','2026-03-01')"
    )
    assert service.list_org_members({"userId": 1}, 10, "active", 1, 50)["list"][1]["realName"] == "最新成员姓名"


def test_direct_admin_without_application(members_db):
    members_db.execute("DELETE FROM organization_admin_application")
    row = service.list_org_members({"userId": 1}, 10, "active", 1, 50)["list"][0]
    assert row.get("realName", "missing") is None and row["role"] == "admin"


@pytest.mark.parametrize("user,org", [(2, 10), (1, 20)])
def test_authorization_unchanged(members_db, user, org):
    with pytest.raises(BizError) as error:
        service.list_org_members({"userId": user}, org, "active", 1, 50)
    assert error.value.http_status == 403


def test_application_query_unchanged(members_db):
    rows = service.list_membership_applications({"userId": 1}, 10, "pending", 1, 50)
    assert rows["total"] == 1 and rows["list"][0]["realName"] == "未批准姓名"


def test_review_ties_and_null_time(members_db):
    members_db.execute(
        "INSERT INTO organization_membership_application VALUES (90,2,10,'approved','无审核时间',NULL),(91,2,10,'rejected','驳回姓名','2027-01-01'),(92,2,10,'approved','同时间较新ID','2026-01-01')"
    )
    assert service.list_org_members({"userId": 1}, 10, "active", 1, 50)["list"][1]["realName"] == "同时间较新ID"


@pytest.mark.parametrize("value", ["+86 138-0013-8000", "U202600001", "123456", "user123", "测试用户", "  "])
def test_unreliable_profile_fallback_rejected(value):
    assert service._member_display_name(value, "U202600001") is None


def test_query_plan_preserves_bounded_member_rows(members_db):
    service.list_org_members({"userId": 1}, 10, "active", 1, 3)
    query = members_db.query.decode("utf-8")
    members_db.execute("EXPLAIN (ANALYZE, FORMAT JSON) " + query)
    plan = members_db.fetchone()["QUERY PLAN"][0]["Plan"]
    assert plan["Actual Rows"] == 3
    assert plan["Node Type"] == "Limit"
