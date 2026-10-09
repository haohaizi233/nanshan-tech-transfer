"""Authenticated organization certification and scoped membership workflows."""

from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Request

from core.middleware import admin_identity, identity, org_admin_identity
from core.pagination import parse_page_args
from core.response import get_request_id, success
from modules.membership import schemas, service

router = APIRouter(prefix="/api/tech-transfer/v1", tags=["organization-membership"])
ApplicationStatus = Optional[Literal["pending", "approved", "rejected", "cancelled"]]
MembershipStatus = Optional[Literal["active", "revoked"]]


@router.get("/me/organization-memberships")
def my_memberships(request: Request, user: dict = Depends(identity)):
    page, page_size, _ = parse_page_args(request)
    return success(service.list_my_memberships(user, page, page_size))


@router.get("/me/organization-certification")
def my_organization_certification(user: dict = Depends(identity)):
    return success(service.get_my_organization_certification(user))


@router.get("/me/organization-membership-applications")
def my_membership_applications(
    request: Request, status: ApplicationStatus = None, user: dict = Depends(identity)
):
    page, page_size, _ = parse_page_args(request)
    return success(service.list_my_membership_applications(user, status, page, page_size))


@router.post("/me/organization-membership-applications")
def apply_membership(body: schemas.MembershipApplicationRequest, user: dict = Depends(identity)):
    return success(service.apply_membership(user, body.model_dump(exclude_unset=True)))


@router.post("/me/organization-membership-applications/{application_id}/cancel")
def cancel_membership(application_id: int, body: schemas.VersionRequest, user: dict = Depends(identity)):
    return success(service.cancel_membership_application(user, application_id, body.version, request_id=get_request_id()))


@router.post("/me/organization-admin-applications")
def apply_admin(body: schemas.OrganizationAdminApplicationRequest, user: dict = Depends(identity)):
    return success(service.apply_organization_admin(user, body.model_dump(exclude_unset=True)))


@router.post("/me/organization-applications")
def apply_organization(body: schemas.OrganizationApplicationRequest, user: dict = Depends(identity)):
    return success(service.apply_organization(user, body.model_dump(exclude_unset=True)))


@router.get("/org-admin/members")
def org_members(request: Request, orgId: int = Query(..., ge=1), status: MembershipStatus = None,
                admin: dict = Depends(org_admin_identity)):
    page, page_size, _ = parse_page_args(request)
    return success(service.list_org_members(admin, orgId, status, page, page_size))


@router.get("/org-admin/membership-applications")
def membership_applications(request: Request, orgId: int = Query(..., ge=1), status: ApplicationStatus = None,
                            admin: dict = Depends(org_admin_identity)):
    page, page_size, _ = parse_page_args(request)
    return success(service.list_membership_applications(admin, orgId, status, page, page_size))


@router.post("/org-admin/membership-applications/{application_id}/approve")
def approve_membership(application_id: int, body: schemas.MembershipReviewRequest, admin: dict = Depends(org_admin_identity)):
    return success(service.approve_membership_application(admin, application_id, body.version, request_id=get_request_id()))


@router.post("/org-admin/membership-applications/{application_id}/reject")
def reject_membership(application_id: int, body: schemas.MembershipRejectionRequest, admin: dict = Depends(org_admin_identity)):
    return success(service.reject_membership_application(admin, application_id, body.version, body.reason, request_id=get_request_id()))


@router.post("/org-admin/members/{membership_id}/revoke")
def revoke_member(membership_id: int, body: schemas.MembershipRevocationRequest, admin: dict = Depends(org_admin_identity)):
    return success(service.revoke_membership(admin, membership_id, body.version, body.reason, request_id=get_request_id()))


@router.get("/admin/certification-applications")
def certification_applications(request: Request, status: ApplicationStatus = None, admin: dict = Depends(admin_identity)):
    page, page_size, _ = parse_page_args(request)
    return success(service.list_all_certification_applications(admin, status, page, page_size))


@router.get("/admin/organization-applications")
def organization_applications(request: Request, status: ApplicationStatus = None, admin: dict = Depends(admin_identity)):
    page, page_size, _ = parse_page_args(request)
    return success(service.list_organization_applications(admin, status, page, page_size))


@router.get("/admin/organization-membership-applications")
def organization_membership_applications(request: Request, status: ApplicationStatus = None,
                                         admin: dict = Depends(admin_identity)):
    page, page_size, _ = parse_page_args(request)
    return success(service.list_organization_membership_applications(admin, status, page, page_size))


@router.post("/admin/organization-membership-applications/{application_id}/approve")
def approve_organization_membership(application_id: int, body: schemas.MembershipReviewRequest,
                                    admin: dict = Depends(admin_identity)):
    return success(service.approve_membership_application(admin, application_id, body.version, request_id=get_request_id()))


@router.post("/admin/organization-membership-applications/{application_id}/reject")
def reject_organization_membership(application_id: int, body: schemas.MembershipRejectionRequest,
                                   admin: dict = Depends(admin_identity)):
    return success(service.reject_membership_application(admin, application_id, body.version, body.reason, request_id=get_request_id()))


@router.post("/admin/organization-applications/{application_id}/approve")
def approve_organization(application_id: int, body: schemas.OrganizationApplicationReviewRequest, admin: dict = Depends(admin_identity)):
    return success(service.approve_organization_application(admin, application_id, body.version, request_id=get_request_id()))


@router.post("/admin/organization-applications/{application_id}/reject")
def reject_organization(application_id: int, body: schemas.OrganizationApplicationRejectionRequest, admin: dict = Depends(admin_identity)):
    return success(service.reject_organization_application(admin, application_id, body.version, body.reason, request_id=get_request_id()))


@router.get("/admin/organization-admin-applications")
def admin_applications(request: Request, status: ApplicationStatus = None, admin: dict = Depends(admin_identity)):
    page, page_size, _ = parse_page_args(request)
    return success(service.list_organization_admin_applications(admin, status, page, page_size))


@router.post("/admin/organization-admin-applications/{application_id}/approve")
def approve_admin_application(application_id: int, body: schemas.OrganizationAdminReviewRequest, admin: dict = Depends(admin_identity)):
    return success(service.approve_organization_admin_application(admin, application_id, body.version, request_id=get_request_id()))


@router.post("/admin/organization-admin-applications/{application_id}/reject")
def reject_admin_application(application_id: int, body: schemas.OrganizationAdminRejectionRequest, admin: dict = Depends(admin_identity)):
    return success(service.reject_organization_admin_application(admin, application_id, body.version, body.reason, request_id=get_request_id()))


@router.post("/admin/organization-memberships/{membership_id}/grant-admin")
def grant_admin(membership_id: int, body: schemas.OrganizationAdminGrantRequest, admin: dict = Depends(admin_identity)):
    return success(service.grant_organization_admin(admin, membership_id, body.version, request_id=get_request_id()))


@router.post("/admin/organization-memberships/{membership_id}/revoke-admin")
def revoke_admin(membership_id: int, body: schemas.OrganizationAdminRevocationRequest, admin: dict = Depends(admin_identity)):
    return success(service.revoke_organization_admin(admin, membership_id, body.version, body.reason, request_id=get_request_id()))
