from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ApprovalPackage:
    manager_email_subject: str
    manager_email_body: str
    client_email_subject: str
    client_email_body: str


class ApprovalService:
    def build_package(
        self,
        property_name: str,
        manager_email: str,
        client_email: str,
        report_url: str,
        approve_url: str,
        reject_url: str,
    ) -> ApprovalPackage:
        manager_subject = f"Approval Required: DDR Report for {property_name}"
        manager_body = (
            f"Hello,\n\n"
            f"The DDR report for {property_name} is ready for review.\n\n"
            f"Report: {report_url}\n"
            f"Approve: {approve_url}\n"
            f"Reject / Request changes: {reject_url}\n\n"
            f"Manager email: {manager_email}\n"
            f"Client email after approval: {client_email}\n"
        )
        client_subject = f"Detailed Diagnosis Report for {property_name}"
        client_body = (
            f"Hello,\n\n"
            f"Please find the approved DDR report for {property_name}.\n\n"
            f"Report: {report_url}\n"
        )
        return ApprovalPackage(
            manager_email_subject=manager_subject,
            manager_email_body=manager_body,
            client_email_subject=client_subject,
            client_email_body=client_body,
        )
