# Organization Membership Design

## Goal

Separate platform accounts from organization certification. A registered user remains able to publish, connect, favorite, and maintain a profile regardless of certification. A formal organization relationship is established only by an active membership referencing `organization.id`; free-text organization names never create or infer that relationship.

## Existing Boundaries

- `app_user` remains the only account and login system.
- `organization` remains the canonical organization table for content ownership and certification. `institution` remains the separate capital/service directory and is not used for memberships.
- `user_role` continues to hold system-level roles only. The existing `admin` role remains the System Admin check.
- `user_profile` remains profile data. Its free-text unit/company value is presentation data and is not an authority field.

## Data Model

Add `organization_membership` with an organization and user foreign key, role (`member` or `admin`), status (`active` or `revoked`), department, title, verification and revocation metadata, timestamps, and optimistic-lock `version`.

It supports multi-organization membership. A partial unique index permits at most one active membership per `(user_id, org_id)` while preserving revoked history.

Add three application tables, each with `pending`, `approved`, `rejected`, and `cancelled` status, review metadata, timestamps, and version:

- `organization_membership_application` for joining an existing organization.
- `organization_admin_application` for requesting an organization-admin grant.
- `organization_application` for proposing a new canonical organization.

The migration is add-only. It does not create memberships from existing profile fields or historical content. It adds a clearly named free-text company/unit field to `user_profile` where needed while retaining legacy fields for client compatibility.

## Identity and Authorization

`admin_identity` remains the real-time System Admin check against `user_role`.

A new real-time organization-admin dependency queries active `organization_membership` rows with `role='admin'`. Every organization-admin operation independently verifies its resource's `org_id` belongs to those rows. Client-supplied organization IDs never grant access.

The authorization matrix is:

| Ability | Unverified | Member | Org Admin | System Admin |
|---|---:|---:|---:|---:|
| Publish demand or achievement | yes | yes | yes | yes |
| Propose cooperation | yes | yes | yes | yes |
| Apply to join an organization | yes | yes | yes | yes |
| Review own organization's member applications | no | no | yes | yes |
| Revoke own organization's ordinary member | no | no | yes | yes |
| Grant/revoke organization admin | no | no | no | yes |
| Approve organization creation | no | no | no | yes |
| View global users | no | no | no | yes |

## Workflows

### Join an existing organization

The client searches active `organization` rows by keyword and submits the selected `orgId`. The service returns 409 for an existing pending application or active membership. Approval is performed by an active administrator of that organization, or by a System Admin when no such administrator exists. Approval atomically updates the application, creates or reactivates a member membership, and records the audit event.

### Apply for a new organization

The client submits organization details without creating a canonical row. Only a System Admin may approve. One transaction creates `organization`, approves the application, creates an active administrator membership for the applicant, and records audit data. Rejection creates neither organization nor membership.

### Organization administration

An existing user may request organization-admin status. System Admin is the final approver. Organization admins may list their own members and applications, approve/reject their own membership applications, and revoke only active `member` memberships. They cannot grant, revoke, or modify administrator memberships.

### Revoke and reapply

Revocation changes only a membership to `revoked` and records who, when, why, and a new version. It never disables `app_user` or ordinary platform capabilities. Rejected and revoked applicants may apply again; active and pending states block duplicates.

## API Shape

Use the existing `/api/tech-transfer/v1` style. Add equivalent endpoints for:

- public authenticated organization search using the existing canonical `organization` domain;
- current-user certification state and application submission/cancellation;
- scoped `/org-admin` member and member-application list/review/revoke operations;
- System Admin list/review operations for organization and organization-admin applications, and explicit admin grant/revoke actions.

Every state-changing approval, rejection, grant, or revocation requires `version`, uses `WHERE id = ? AND version = ?`, and returns 409 for stale or invalid state. Error responses use the existing 400/403/404/409/422 contract. Audits record organization, subject user, application/membership, transition, and actor in the same transaction.

## Content and Assisted Cooperation

Demand and achievement create/update paths accept `orgId` only if the current user has active membership for that organization. Otherwise they return a business validation/authorization error. `orgName`, company text, and historical snapshots are retained only for display; they do not create an organization or membership.

Historical content is unchanged. Admin-entered content continues to use canonical organization ownership and existing assisted-cooperation behavior: a real platform owner produces direct cooperation; no owner produces assisted cooperation. Organization membership does not make an ordinary member an official organization publisher.

## Client and Admin UI

The mini-program profile separates “单位/公司名称（仅展示）” from “认证机构”. It exposes certification state, search-and-select joining, organization onboarding, and an organization-management entry only for organization admins.

The system-admin user view separates free-text unit, certified organization(s), organization role, certification status, and system role. Organization detail includes administrator, certified-member, and pending-application information. Organization-admin menus expose only scoped organization data; backend checks remain authoritative.

## Tests and Verification

Add `test_organization_membership.py` for free-text non-binding, search selection, duplicate prevention, member approval/rejection, cross-organization isolation, revoke/reapply, organization onboarding, System Admin-only administrator grants, and forged content `orgId` rejection.

Run this test alongside the requested achievement, demand, admin, AI, chain, database-session, error-contract, institution, interaction, and isolation suites; then run release smoke, Python compilation, OpenAPI/admin mapping checks, and the mini-program build inspection.

## Non-Goals

This work does not add a second account system, automatic name or alias certification, LDAP/SAML/SSO/SCIM, a generic approval engine, organization-admin entries in `user_role`, or implicit migration of historical content into organization ownership.
