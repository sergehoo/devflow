"""
Finance : RBAC de facturation (vues historiques, AJAX, pont React), cockpit
financier et allocation (budget.view), éditeur de facture (lignes, totaux,
paiements). Isolation multi-tenant.

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test python manage.py test project.tests_api_finance
"""

import json
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from project import models as dm

STORAGES = {**settings.STORAGES, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}


@override_settings(STORAGES=STORAGES, AI_BACKEND="none")
class FinanceFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        mk = lambda n: User.objects.create_user(n, f"{n}@x.test", "pw")  # noqa: E731
        cls.owner, cls.pm, cls.member, cls.bob = (mk(n) for n in ("owner", "pm", "member", "bob"))
        cls.ws = dm.Workspace.objects.create(name="Alpha", owner=cls.owner)
        cls.other = dm.Workspace.objects.create(name="Beta", owner=cls.bob)
        for u, ws in ((cls.owner, cls.ws), (cls.pm, cls.ws), (cls.member, cls.ws), (cls.bob, cls.other)):
            dm.UserProfile.objects.update_or_create(user=u, defaults={"workspace": ws})
            dm.TeamMembership.objects.create(user=u, workspace=ws)
        dm.WorkspaceRoleAssignment.objects.create(user=cls.pm, workspace=cls.ws, role="PROJECT_MANAGER")
        cls.project = dm.Project.objects.create(workspace=cls.ws, name="Portail")
        cls.client_ = dm.InvoiceClient.objects.create(workspace=cls.ws, name="Client SA")
        cls.invoice = dm.Invoice.objects.create(workspace=cls.ws, client=cls.client_, project=cls.project)
        cls.line = dm.InvoiceLine.objects.create(invoice=cls.invoice, label="Développement", quantity=Decimal("2"), unit_price=Decimal("500"))
        cls.foreign = dm.Invoice.objects.create(workspace=cls.other, client=dm.InvoiceClient.objects.create(workspace=cls.other, name="X"))

    def web(self, user):
        self.client.force_login(user)
        return self.client

    def api(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c


class BillingRbacTests(FinanceFixture):
    def test_member_cannot_issue_pay_or_edit_invoices_through_any_interface(self):
        inv = self.invoice
        self.assertEqual(self.web(self.member).post(f"/billing/invoices/{inv.pk}/issue/").status_code, 403)
        self.assertEqual(self.web(self.member).post(f"/billing/invoices/{inv.pk}/payments/create/", {"amount": "10"}).status_code, 403)
        self.assertEqual(self.web(self.member).get("/billing/invoices/").status_code, 403)
        self.assertEqual(self.api(self.member).post(f"/api/v1/resources/invoice/{inv.pk}/actions/issue/", {"next": "/"}, format="multipart").status_code, 403)
        self.assertEqual(self.api(self.member).post(f"/api/v1/invoices/{inv.pk}/lines/", {"label": "x"}, format="json").status_code, 403)
        inv.refresh_from_db()
        self.assertEqual(inv.status, dm.Invoice.Status.DRAFT)

    def test_project_manager_reads_but_cannot_write(self):
        pm = self.api(self.pm)
        self.assertEqual(pm.get(f"/api/v1/invoices/{self.invoice.pk}/lines/").status_code, 200)
        self.assertEqual(pm.patch(f"/api/v1/invoice-lines/{self.line.pk}/", {"quantity": "9"}, format="json").status_code, 403)
        self.assertEqual(pm.get(f"/api/v1/invoices/{self.invoice.pk}/payments/").json()["can_edit"], False)
        self.assertEqual(self.web(self.pm).get(f"/billing/invoices/{self.invoice.pk}/").status_code, 200)

    def test_owner_edits_lines_totals_and_records_payment(self):
        owner = self.api(self.owner)
        res = owner.post(f"/api/v1/invoices/{self.invoice.pk}/lines/", {"label": "Recette", "quantity": "1", "unit_price": "250"}, format="json")
        self.assertIn(res.status_code, (200, 201), res.content)
        res = owner.patch(f"/api/v1/invoice-lines/{self.line.pk}/", {"quantity": "3"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(owner.patch(f"/api/v1/invoices/{self.invoice.pk}/totals/", {"discount_amount": "100"}, format="json").status_code, 200)
        lines = owner.get(f"/api/v1/invoices/{self.invoice.pk}/lines/").json()
        self.assertEqual(len(lines["lines"]), 2)
        form = owner.get(f"/api/v1/invoices/{self.invoice.pk}/payments/").json()["form"]["fields"]
        payload = {}
        for f in form:
            if f["type"] in ("select",) and f["choices"]:
                payload[f["name"]] = next(c["value"] for c in f["choices"] if c["value"])
            elif f["name"] == "amount":
                payload["amount"] = "100"
            elif f["type"] == "date":
                payload[f["name"]] = "2026-11-10"
        res = owner.post(f"/api/v1/invoices/{self.invoice.pk}/payments/", payload, format="multipart")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(len(owner.get(f"/api/v1/invoices/{self.invoice.pk}/payments/").json()["payments"]), 1)

    def test_cross_tenant_invoice_is_unreachable(self):
        self.assertEqual(self.api(self.owner).get(f"/api/v1/invoices/{self.foreign.pk}/lines/").status_code, 404)
        self.assertEqual(self.api(self.owner).get(f"/api/v1/invoices/{self.foreign.pk}/payments/").status_code, 404)
        self.assertEqual(self.web(self.owner).post(f"/billing/invoices/{self.foreign.pk}/issue/").status_code, 404)


class PortfolioTests(FinanceFixture):
    def test_portfolio_requires_budget_view_and_is_scoped(self):
        res = self.api(self.owner).get("/api/v1/finance/portfolio/", {"workspace": self.ws.pk})
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual([r["project"]["name"] for r in res.json()["rows"]], ["Portail"])
        self.assertEqual(self.api(self.pm).get("/api/v1/finance/portfolio/", {"workspace": self.ws.pk}).status_code, 200)
        self.assertEqual(self.api(self.member).get("/api/v1/finance/portfolio/", {"workspace": self.ws.pk}).status_code, 403)
        self.assertEqual(self.api(self.owner).get("/api/v1/finance/portfolio/", {"workspace": self.other.pk}).status_code, 404)
        self.assertEqual(self.web(self.member).get(f"/workspaces/{self.ws.pk}/financial-ai/portfolio/").status_code, 403)

    def test_allocation_advice_uses_heuristics_without_ai_key(self):
        res = self.api(self.owner).get("/api/v1/finance/allocation/", {"workspace": self.ws.pk})
        self.assertEqual(res.status_code, 200, res.content)
        self.assertIn("recommendations", res.json())
        self.assertEqual(self.api(self.member).get("/api/v1/finance/allocation/", {"workspace": self.ws.pk}).status_code, 403)


class RealBrowserCsrfTests(FinanceFixture):
    """Avec la vérification CSRF active (navigateur réel), le corps JSON atteint bien la vue historique."""

    def test_line_payload_survives_csrf_check(self):
        from django.test import Client

        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.owner)
        browser.get("/api/v1/auth/csrf/")
        token = browser.cookies["csrftoken"].value
        res = browser.post(f"/api/v1/invoices/{self.invoice.pk}/lines/", json.dumps({"label": "Recette", "quantity": "1", "unit_price": "250"}),
                           content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual((res.json()["line"]["label"], Decimal(res.json()["line"]["unit_price"])), ("Recette", Decimal("250")))
