"""Live PostgreSQL assertions for the organization-membership schema."""
import sys

import db


PASS = 0
FAIL = 0

TABLES = (
    "organization_membership",
    "organization_membership_application",
    "organization_admin_application",
    "organization_application",
)
MEMBERSHIP_COLUMNS = {"org_id", "user_id", "role", "status", "version"}


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PASS] {name}")
    else:
        FAIL += 1
        print(f"[FAIL] {name} — {detail}")


def main():
    with db.get_cursor() as cur:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = ANY(%s)
            """,
            (list(TABLES),),
        )
        existing_tables = {row["table_name"] for row in cur.fetchall()}

        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'organization_membership'
            """
        )
        membership_columns = {row["column_name"] for row in cur.fetchall()}

    for table_name in TABLES:
        check(f"table {table_name} exists", table_name in existing_tables)
    check(
        "organization_membership has required columns",
        MEMBERSHIP_COLUMNS <= membership_columns,
        f"missing: {sorted(MEMBERSHIP_COLUMNS - membership_columns)}",
    )

    print(f"RESULT: {PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
