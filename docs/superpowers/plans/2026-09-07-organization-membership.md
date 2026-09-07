# Organization Membership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement organization certification, scoped organization administration, and canonical organization ownership without restricting ordinary platform users.

**Architecture:** Retain `app_user` for accounts and `organization` for canonical content organizations. Add membership and application tables, expose them through a focused membership service, and enforce active membership for user-authored content association. System administration remains global `user_role.admin`; organization administration is a real-time, organization-scoped membership check.

**Tech Stack:** Python 3/FastAPI, PostgreSQL/psycopg2, Vue 3 admin, uni-app/Vue mini-program, existing script-based API regression tests.

**Spec:** `docs/superpowers/specs/2026-09-07-organization-membership-design.md`

## Global Constraints

- `app_user` remains the sole account and login system.
- Canonical certification organizations use existing `organization`, never `institution`.
- `user_role` stores System Admin only; `organization_membership.role` stores `member` or `admin` only.
- Free-text company/unit data never creates, guesses, or grants a formal organization relationship.
- Unverified users retain publish, connect, favorite, and profile capabilities.
- All approval/grant/revoke writes require `version`, use optimistic locking, and write audit data in the same transaction.
- Do not alter existing historical migrations or create memberships from legacy profile/content text.
- Preserve pre-existing dirty working-tree changes outside this feature.

---

## File Structure

| File | Responsibility |
|---|---|
| `tech-transfer-service/migrations/pg/009_organization_membership.sql` | Add-only membership/application schema, constraints, indexes, and comments. |
| `tech-transfer-service/modules/membership/service.py` | Validation, application state machines, scoped reads, transactional reviews, grants, revokes, and response mapping. |
| `tech-transfer-service/modules/membership/schemas.py` | Pydantic request validation for all membership flows. |
| `tech-transfer-service/routes/membership.py` | Authenticated user, org-admin, and System Admin API endpoints. |
| `tech-transfer-service/core/middleware.py` | Real-time active organization-admin identity helpers. |
| `tech-transfer-service/modules/identity/service.py` | Profile response mapping for free text and formal memberships. |
| `tech-transfer-service/modules/profile/service.py` | Profile update validation that treats company text as non-authoritative. |
| `tech-transfer-service/modules/demand/service.py` | Active-membership checks and free-text snapshots on demand create/update. |
| `tech-transfer-service/modules/achievement/service.py` | Active-membership checks and free-text snapshots on achievement create/update. |
| `tech-transfer-service/app.py` | Mount membership router. |
| `tech-transfer-service/test_organization_membership.py` | End-to-end behavior and authorization regression coverage. |
| `tech-transfer-service/docs/organization-membership.md` | Business model, flows, matrix, API and assisted-cooperation documentation. |
| `tech-transfer-service/docs/admin-api-ui-mapping.md` | Extend admin endpoint-to-screen mapping. |
| `南山小程序/南山/common/organization-membership-api.js` | Mini-program membership API client. |
| `南山小程序/南山/subpackages/tech-transfer/pages/mine/mine.vue` | Profile split, certification state, entry points and application UX. |
| `nanshan-frontend/src/views/admin/UserView.vue` | Display free text separately from memberships. |
| `nanshan-frontend/src/views/admin/UserView.vue` | System-admin user detail, membership/admin review controls, and separated identity display. |

## Task 1: Add the additive PostgreSQL schema

**Files:**
- Create: `tech-transfer-service/migrations/pg/009_organization_membership.sql`
- Test: `tech-transfer-service/test_organization_membership.py`

**Interfaces:**
- Produces tables `organization_membership`, `organization_membership_application`, `organization_admin_application`, and `organization_application`.
- Produces partial unique index `uq_active_organization_membership` on `(user_id, org_id)` for `status='active'`.

- [ ] **Step 1: Write the failing schema assertions**

```python
def test_membership_schema_exists():
    required = {
        'organization_membership',
        'organization_membership_application',
        'organization_admin_application',
        'organization_application',
    }
    rows = db_query("SELECT tablename FROM pg_tables WHERE schemaname='public'")
    assert required <= {row['tablename'] for row in rows}

    columns = db_query("SELECT column_name FROM information_schema.columns "
                       "WHERE table_name='organization_membership'")
    assert {'org_id', 'user_id', 'role', 'status', 'version'} <= {
        row['column_name'] for row in columns
    }
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `python test_organization_membership.py`

Expected: FAIL because the tables do not exist.

- [ ] **Step 3: Create an idempotent add-only migration**

```sql
CREATE TABLE IF NOT EXISTS public.organization_membership (
    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    org_id BIGINT NOT NULL REFERENCES public.organization(id) ON UPDATE CASCADE,
    user_id BIGINT NOT NULL REFERENCES public.app_user(id) ON UPDATE CASCADE,
    role VARCHAR(16) NOT NULL CHECK (role IN ('member', 'admin')),
    status VARCHAR(16) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked')),
    department VARCHAR(128), title VARCHAR(128),
    verified_by_user_id BIGINT REFERENCES public.app_user(id) ON UPDATE CASCADE,
    verified_at TIMESTAMPTZ, revoked_by_user_id BIGINT REFERENCES public.app_user(id) ON UPDATE CASCADE,
    revoked_at TIMESTAMPTZ, revoke_reason TEXT,
    version INT NOT NULL DEFAULT 1, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_active_organization_membership
    ON public.organization_membership(user_id, org_id) WHERE status='active';
```

Create application tables with `pending/approved/rejected/cancelled` checks, their domain fields from the spec, `reviewed_by_user_id`, `reviewed_at`, `review_reason`, timestamps, and `version`; add the search indexes stated in the spec. Add update triggers using existing `set_updated_at()`.

- [ ] **Step 4: Apply migration to the test database and rerun the focused test**

Run: `psql -h 127.0.0.1 -U postgres -d tech_transfer -v ON_ERROR_STOP=1 -f migrations/pg/009_organization_membership.sql; python test_organization_membership.py`

Expected: schema assertions PASS.

- [ ] **Step 5: Commit the schema task**

```bash
git add tech-transfer-service/migrations/pg/009_organization_membership.sql tech-transfer-service/test_organization_membership.py
git commit -m "feat: add organization membership schema"
```

## Task 2: Implement membership domain service and real-time identity

**Files:**
- Create: `tech-transfer-service/modules/membership/__init__.py`
- Create: `tech-transfer-service/modules/membership/service.py`
- Create: `tech-transfer-service/modules/membership/schemas.py`
- Modify: `tech-transfer-service/core/middleware.py`
- Test: `tech-transfer-service/test_organization_membership.py`

**Interfaces:**
- Produces `active_membership_org_ids(user_id: int) -> set[int]` and `assert_active_membership(cur, user_id: int, org_id: int) -> None`.
- Produces `org_admin_identity(request) -> dict` and `assert_org_admin_for(cur, admin: dict, org_id: int) -> None`.
- Produces application, review, grant, and revoke service functions consumed by Task 3.

- [ ] **Step 1: Write failing service/API tests for isolation and membership rules**

```python
def test_org_admin_cannot_review_another_organization_application():
    response = requests.post(
        f'{BASE}/org-admin/membership-applications/{org2_application_id}/approve',
        headers=org1_admin_headers,
        json={'version': 1}, timeout=10,
    )
    assert response.status_code in (403, 404)

def test_active_membership_is_required_for_content_organization():
    response = requests.post(
        f'{BASE}/demands', headers=ordinary_user_headers,
        json={'title': 'T', 'description': 'D', 'orgId': org2_id}, timeout=10,
    )
    assert response.status_code in (400, 403)
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `python test_organization_membership.py`

Expected: FAIL because no membership APIs or enforcement exist.

- [ ] **Step 3: Implement focused domain primitives and request schemas**

```python
def assert_active_membership(cur, user_id: int, org_id: int) -> None:
    cur.execute("""SELECT 1 FROM organization_membership
                   WHERE user_id=%s AND org_id=%s AND status='active'""", (user_id, org_id))
    if not cur.fetchone():
        raise forbidden('无权关联该认证机构')

def assert_org_admin_for(cur, admin: dict, org_id: int) -> None:
    cur.execute("""SELECT 1 FROM organization_membership
                   WHERE user_id=%s AND org_id=%s AND role='admin' AND status='active'""",
                (admin['userId'], org_id))
    if not cur.fetchone() and not is_system_admin(cur, admin['userId']):
        raise forbidden('无权管理该机构')
```

Make every review function open `transaction()`, update the application with `WHERE id=%s AND version=%s AND status='pending'`, create/reactivate the membership, call `audit_record(..., cur=cur.cursor())`, and return 409 when no row was changed.

- [ ] **Step 4: Rerun the focused service tests**

Run: `python test_organization_membership.py`

Expected: the isolated authorization assertions PASS.

- [ ] **Step 5: Commit the domain task**

```bash
git add tech-transfer-service/modules/membership tech-transfer-service/core/middleware.py tech-transfer-service/test_organization_membership.py
git commit -m "feat: add membership domain authorization"
```

## Task 3: Expose user, organization-admin, and System Admin APIs

**Files:**
- Create: `tech-transfer-service/routes/membership.py`
- Modify: `tech-transfer-service/app.py`
- Test: `tech-transfer-service/test_organization_membership.py`

**Interfaces:**
- Consumes Task 2 service functions and Pydantic schemas.
- Produces `/organizations/search`, `/me/organization-*`, `/org-admin/*`, and `/admin/organization-*` endpoints.

- [ ] **Step 1: Write failing endpoint-flow tests**

```python
def test_join_existing_organization_and_duplicate_guard():
    first = requests.post(f'{BASE}/me/organization-membership-applications',
                          headers=user_headers, json={'orgId': org_id, 'department': '研发'}, timeout=10)
    assert first.status_code == 200
    again = requests.post(f'{BASE}/me/organization-membership-applications',
                          headers=user_headers, json={'orgId': org_id}, timeout=10)
    assert again.status_code == 409

def test_new_organization_approval_creates_admin_membership_atomically():
    created = requests.post(f'{BASE}/me/organization-applications', headers=user_headers,
                            json={'requestedName': '新机构', 'requestedType': 'enterprise'}, timeout=10)
    approved = requests.post(f"{BASE}/admin/organization-applications/{created.json()['data']['id']}/approve",
                             headers=system_admin_headers, json={'version': 1}, timeout=10)
    assert approved.status_code == 200
```

- [ ] **Step 2: Run endpoint tests to verify they fail**

Run: `python test_organization_membership.py`

Expected: FAIL with route-not-found responses.

- [ ] **Step 3: Add routes with explicit action endpoints**

```python
@router.post('/org-admin/membership-applications/{application_id}/approve')
def approve_membership_application(application_id: int, body: VersionRequest,
                                   admin: dict = Depends(org_admin_identity)):
    return success(approve_membership_application_service(admin, application_id, body.version))

@router.post('/admin/organization-applications/{application_id}/approve')
def approve_organization_application(application_id: int, body: VersionRequest,
                                     admin: dict = Depends(admin_identity)):
    return success(approve_organization_application_service(admin, application_id, body.version))
```

Search only active `organization` rows by keyword and pagination. Do not use `institution`, `LIKE`-based automatic association, or a generic status PATCH endpoint.

- [ ] **Step 4: Run the complete membership test script**

Run: `python test_organization_membership.py`

Expected: join, approve, reject, revoke, reapply, new organization, System Admin grant/revoke, stale version, audit, and cross-organization tests PASS.

- [ ] **Step 5: Commit the API task**

```bash
git add tech-transfer-service/routes/membership.py tech-transfer-service/app.py tech-transfer-service/test_organization_membership.py
git commit -m "feat: expose organization membership APIs"
```

## Task 4: Make profile and content associations safe

**Files:**
- Modify: `tech-transfer-service/modules/identity/service.py`
- Modify: `tech-transfer-service/modules/profile/service.py`
- Modify: `tech-transfer-service/modules/demand/service.py`
- Modify: `tech-transfer-service/modules/achievement/service.py`
- Test: `tech-transfer-service/test_organization_membership.py`
- Test: `tech-transfer-service/test_demand_api.py`
- Test: `tech-transfer-service/test_achievement_write_api.py`

**Interfaces:**
- Produces `/me` response fields `companyText` and `organizationMemberships`.
- Consumes `assert_active_membership` for every user-authored non-null `orgId`.

- [ ] **Step 1: Write failing non-binding and forged-organization tests**

```python
def test_company_text_does_not_create_membership():
    profile = requests.patch(f'{BASE}/me/profile', headers=user_headers,
                             json={'companyText': '河南科枝大学', 'version': 1}, timeout=10)
    assert profile.status_code == 200
    assert profile.json()['data']['organizationMemberships'] == []

def test_legacy_org_name_does_not_create_canonical_organization():
    before = db_query('SELECT COUNT(*) AS c FROM organization')[0]['c']
    response = requests.post(f'{BASE}/demands', headers=user_headers,
                             json={'title': '文本机构', 'description': '内容', 'orgName': '不会自动创建'}, timeout=10)
    assert response.status_code in (200, 201)
    after = db_query('SELECT COUNT(*) AS c FROM organization')[0]['c']
    assert after == before
```

- [ ] **Step 2: Run tests to verify current behavior fails**

Run: `python test_organization_membership.py; python test_demand_api.py; python test_achievement_write_api.py`

Expected: the automatic `orgName` creation assertion FAILS before implementation.

- [ ] **Step 3: Replace authority behavior while retaining compatibility fields**

```python
if 'orgId' in body and body['orgId'] is not None:
    assert_active_membership(cur, user_id, int(body['orgId']))
if 'orgName' in body:
    fields['org_name_snapshot'] = normalize_optional_text(body['orgName'], 128)
```

Remove the demand name-to-organization resolver from create/update paths. Add `demand.org_name_snapshot` in the Task 1 migration because demand has no existing display-only organization-name field; continue using existing `achievement.source_org_name` as the achievement snapshot. Return canonical memberships from `build_user_response`; never derive them from `user_profile.org_id`.

- [ ] **Step 4: Run focused and existing content tests**

Run: `python test_organization_membership.py; python test_demand_api.py; python test_achievement_write_api.py`

Expected: PASS, with unverified users still able to publish without `orgId`.

- [ ] **Step 5: Commit the safety task**

```bash
git add tech-transfer-service/modules/identity/service.py tech-transfer-service/modules/profile/service.py tech-transfer-service/modules/demand/service.py tech-transfer-service/modules/achievement/service.py tech-transfer-service/migrations/pg/009_organization_membership.sql tech-transfer-service/test_organization_membership.py
git commit -m "feat: enforce membership for content organizations"
```

## Task 5: Add mini-program certification UI and client

**Files:**
- Create: `南山小程序/南山/common/organization-membership-api.js`
- Modify: `南山小程序/南山/subpackages/tech-transfer/pages/mine/mine.vue`
- Modify: relevant `pages.json` / subpackage routing file after locating the existing mine routes

**Interfaces:**
- Consumes `/me`, organization search, application submission, and org-admin identity responses.
- Produces a profile that visually separates `companyText` and verified memberships.

- [ ] **Step 1: Write a failing component-level/manual acceptance checklist in the existing page test convention**

```text
Given an unverified user with companyText="河南科大"
When the Mine page loads
Then it shows “单位/公司名称：河南科大（仅展示）” and “机构认证：未认证”
And it offers “申请加入已有机构” and “申请机构入驻”
```

- [ ] **Step 2: Verify the current page lacks the required states**

Run: `rg -n "机构认证|申请加入已有机构|申请机构入驻" 南山小程序/南山/subpackages/tech-transfer/pages/mine/mine.vue`

Expected: no matching UI strings.

- [ ] **Step 3: Implement API wrapper and page states**

```javascript
export function searchOrganizations(keyword, page = 1) {
  return apiRequest('GET', `/organizations/search?keyword=${encodeURIComponent(keyword)}&page=${page}`)
}
export function applyForMembership(payload) {
  return apiRequest('POST', '/me/organization-membership-applications', payload)
}
```

Render free-text unit as editable profile data, render certification names solely from `organizationMemberships`, and send the selected `orgId` rather than an organization name. Show the organization-management entry only when an active membership has `role === 'admin'`.

- [ ] **Step 4: Build and inspect generated mini-program output**

Run the repository's existing mini-program build command from its package manifest, then run: `rg -n "机构认证|申请加入已有机构|申请机构入驻" 南山小程序/南山/unpackage/dist/dev/mp-weixin`

Expected: build succeeds and generated assets contain all three strings.

- [ ] **Step 5: Commit the mini-program task**

```bash
git add 南山小程序/南山/common/organization-membership-api.js 南山小程序/南山/subpackages/tech-transfer/pages/mine/mine.vue 南山小程序/南山/pages.json
git commit -m "feat: add organization certification UI"
```

## Task 6: Extend System Admin presentation and mapping

**Files:**
- Modify: `nanshan-frontend/src/views/admin/UserView.vue`
- Modify: `tech-transfer-service/modules/admin/service.py`
- Modify: `tech-transfer-service/routes/admin_ops.py`
- Modify: `tech-transfer-service/docs/admin-api-ui-mapping.md`
- Test: `tech-transfer-service/test_admin_api.py`

**Interfaces:**
- Consumes System Admin organization membership/application endpoint responses from Task 3.
- Produces separated display fields for free-text unit, certified organization(s), organization role/status, and system role.

- [ ] **Step 1: Add failing Admin API assertions**

```python
def test_admin_user_detail_separates_company_text_and_memberships():
    response = requests.get(f'{BASE}/admin/users/{member_user_id}', headers=admin_headers, timeout=10)
    data = response.json()['data']
    assert data['companyText'] == '河南科大'
    assert data['organizationMemberships'][0]['orgName'] == canonical_org_name
    assert data['organizationMemberships'][0]['role'] == 'member'
```

- [ ] **Step 2: Run the affected admin test before changing the API**

Run: `python test_admin_api.py`

Expected: new assertion FAILS because the old response conflates organization data.

- [ ] **Step 3: Extend admin data and views without widening organization-admin authority**

```python
SELECT up.company_text, om.role, om.status, o.org_name
FROM app_user u
LEFT JOIN user_profile up ON up.user_id=u.id
LEFT JOIN organization_membership om ON om.user_id=u.id
LEFT JOIN organization o ON o.id=om.org_id
WHERE u.id=%s
```

Update labels and tables to show “自填单位”, “认证机构”, “机构角色”, “机构认证状态”, and “系统角色”. Add System Admin controls only for explicit organization/admin application review and administrator grant/revoke actions; do not expose global user controls to organization-admin client routes.

- [ ] **Step 4: Run admin tests and frontend build**

Run: `python test_admin_api.py; npm run build`

Expected: both pass.

- [ ] **Step 5: Commit the admin task**

```bash
git add nanshan-frontend/src/views/admin/UserView.vue tech-transfer-service/modules/admin/service.py tech-transfer-service/routes/admin_ops.py tech-transfer-service/docs/admin-api-ui-mapping.md tech-transfer-service/test_admin_api.py
git commit -m "feat: surface organization memberships in admin"
```

## Task 7: Complete documentation, OpenAPI, and full verification

**Files:**
- Create: `tech-transfer-service/docs/organization-membership.md`
- Modify: `docs/architecture/openapi.yaml`
- Modify: `tech-transfer-service/docs/admin-api-ui-mapping.md`
- Modify: `docs/backend-release-verification.md`

**Interfaces:**
- Documents all final Task 1–6 APIs and authorization behavior.

- [ ] **Step 1: Document the implemented system with concrete tables and endpoints**

```markdown
## Free Text vs Canonical Organization

`user_profile.company_text` is a display-only snapshot. A certified organization is an active `organization_membership` and is identified by `org_id`; no text comparison creates a membership.
```

Include the three states, join/new-organization/admin flows, permission matrix, revocation/reapplication rules, scoped authorization, content ownership, and assisted-cooperation relationship.

- [ ] **Step 2: Regenerate/inspect OpenAPI and assert essential paths exist**

Run: `python -c "from app import app; import json; print(json.dumps(app.openapi(), ensure_ascii=False))" > openapi.generated.json; rg -n "organization-membership|organization-applications|org-admin" openapi.generated.json`

Expected: all membership endpoint groups are present with versioned write schemas.

- [ ] **Step 3: Run target and full regression suites**

Run: `python test_organization_membership.py; python test_achievement_api.py; python test_achievement_write_api.py; python test_admin_api.py; python test_ai_api.py; python test_chain.py; python test_db_hardening.py; python test_db_session.py; python test_demand_api.py; python test_error_contract.py; python test_institution_api.py; python test_interaction_api.py; python test_isolation.py`

Expected: every script exits 0.

- [ ] **Step 4: Run release smoke, compilation, and both frontend builds**

Run: `python tools/smoke_release.py; python -m compileall .; npm run build`

Expected: every command exits 0; report any pre-existing external-service failure separately rather than masking it.

- [ ] **Step 5: Commit documentation and verification artifacts**

```bash
git add tech-transfer-service/docs/organization-membership.md tech-transfer-service/docs/admin-api-ui-mapping.md docs/architecture/openapi.yaml docs/backend-release-verification.md
git commit -m "docs: document organization membership system"
```
