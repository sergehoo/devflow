"""
Écran « TJM des collaborateurs » (``/api/v1/finance/rates/``) : droits, isolation,
périodes tarifaires, revalorisation des saisies et archivage.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from project import models as dm

User = get_user_model()
URL = "/api/v1/finance/rates/"


class RateFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("rate-owner", "o@x.test", "pw", first_name="Serge", last_name="OGAH")
        cls.pm = User.objects.create_user("rate-pm", "p@x.test", "pw", first_name="Emmanuel", last_name="Trah")
        cls.dev = User.objects.create_user("rate-dev", "d@x.test", "pw", first_name="Loic", last_name="Demanou")
        cls.ws = dm.Workspace.objects.create(name="Pôle Dev", owner=cls.owner)
        cls.team = dm.Team.objects.create(workspace=cls.ws, name="Backend")
        for user, job in ((cls.owner, "Solution Architect"), (cls.pm, "PM"), (cls.dev, "Senior Developper")):
            dm.UserProfile.objects.create(user=user, workspace=cls.ws)
            dm.TeamMembership.objects.create(user=user, workspace=cls.ws, team=cls.team, job_title=job)
        dm.WorkspaceRoleAssignment.objects.create(user=cls.pm, workspace=cls.ws, role="PROJECT_MANAGER")
        cls.project = dm.Project.objects.create(workspace=cls.ws, name="ANALYTICS HUB", owner=cls.owner)
        # Autre tenant
        cls.bob = User.objects.create_user("rate-bob", "b@x.test", "pw")
        cls.other = dm.Workspace.objects.create(name="Autre", owner=cls.bob)
        dm.UserProfile.objects.update_or_create(user=cls.bob, defaults={"workspace": cls.other})
        cls.bob = User.objects.get(pk=cls.bob.pk)  # profil relu (le signal en a mis un en cache)
        cls.foreign_project = dm.Project.objects.create(workspace=cls.other, name="Secret", owner=cls.bob)

    def api(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def board(self, actor=None, ws=None):
        return self.api(actor or self.owner).get(URL, {"workspace": (ws or self.ws).pk})

    def create(self, actor=None, ws=None, **data):
        payload = {"user": self.dev.pk, "worker_level": "SENIOR", "unit": "DAILY", "cost_rate_amount": "75000",
                   "sale_rate_amount": "175000", "valid_from": "2026-01-01", **data}
        return self.api(actor or self.owner).post(f"{URL}?workspace={(ws or self.ws).pk}", payload, format="json")

    def member(self, body, user):
        return next(m for m in body["members"] if m["user_id"] == user.pk)


class BillingRateScreenTests(RateFixture):
    # -- droits et isolation -------------------------------------------------
    def test_rights(self):
        self.assertEqual(self.board().status_code, 200)
        pm_view = self.board(self.pm)
        self.assertEqual(pm_view.status_code, 200)
        self.assertFalse(pm_view.json()["can_manage"])
        self.assertEqual(self.create(self.pm).status_code, 403)
        self.assertEqual(self.board(self.dev).status_code, 403)  # simple membre : pas de TJM
        self.assertEqual(self.board(self.bob).status_code, 404)  # autre tenant
        self.assertEqual(self.api(self.owner).get(URL).status_code, 400)  # espace requis

    def test_targets_must_belong_to_the_workspace(self):
        res = self.create(user=self.bob.pk)
        self.assertEqual(res.status_code, 400)
        self.assertIn("user", res.json())
        res = self.create(project=self.foreign_project.pk)
        self.assertEqual((res.status_code, "project" in res.json()), (400, True))
        self.assertFalse(dm.BillingRate.objects.exists())
        rate = dm.BillingRate.objects.create(user=self.bob, cost_rate_amount=1, sale_rate_amount=2, valid_from=date(2026, 1, 1))
        self.assertEqual(self.api(self.owner).delete(f"{URL}{rate.pk}/?workspace={self.ws.pk}").status_code, 404)
        self.assertEqual(self.api(self.owner).patch(f"{URL}{rate.pk}/?workspace={self.ws.pk}", {"cost_rate_amount": "9"},
                                                    format="json").status_code, 404)

    # -- périodes ------------------------------------------------------------
    def test_board_and_periods(self):
        body = self.board().json()
        self.assertEqual(body["summary"], {"members": 3, "with_rate": 0, "without_rate": 3, "unvalued_entries": 0})
        self.assertEqual(self.member(body, self.dev)["job_title"], "Senior Developper")

        self.assertEqual(self.create().status_code, 201)
        current = self.member(self.board().json(), self.dev)["current"]
        self.assertEqual((current["daily_cost"], current["daily_sale"], current["margin_percent"]), ("75000.00", "175000.00", 133.3))

        # Nouvelle période : la précédente est close la veille.
        start = timezone.localdate() - timedelta(days=10)
        self.assertEqual(self.create(valid_from=start.isoformat(), cost_rate_amount="80000").status_code, 201)
        rates = dm.BillingRate.objects.filter(user=self.dev).order_by("valid_from")
        self.assertEqual([(r.valid_from, r.valid_to) for r in rates], [(date(2026, 1, 1), start - timedelta(days=1)), (start, None)])
        self.assertEqual(self.member(self.board().json(), self.dev)["current"]["daily_cost"], "80000.00")
        # Même début : remplacement, pas de doublon.
        self.assertEqual(self.create(valid_from=start.isoformat(), cost_rate_amount="82000").status_code, 201)
        self.assertEqual(dm.BillingRate.objects.filter(user=self.dev).count(), 2)
        # Tarif propre à un projet : prioritaire sur ce projet, sans toucher au TJM général.
        self.assertEqual(self.create(valid_from="2026-01-01", project=self.project.pk, cost_rate_amount="90000").status_code, 201)
        self.assertEqual(dm.BillingRate.get_user_daily_cost(self.dev, project=self.project), Decimal("90000.00"))
        self.assertEqual(dm.BillingRate.get_user_daily_cost(self.dev), Decimal("82000.00"))

    def test_validation_messages(self):
        res = self.create(cost_rate_amount="abc")
        self.assertEqual((res.status_code, "cost_rate_amount" in res.json()), (400, True))
        res = self.create(valid_from="2026-03-01", valid_to="2026-02-01")
        self.assertEqual((res.status_code, "valid_to" in res.json()), (400, True))
        res = self.create(sale_rate_amount="50000")  # vente < coût : règle du modèle, message lisible
        self.assertEqual((res.status_code, "sale_rate_amount" in res.json()), (400, True))

    # -- revalorisation et archivage ----------------------------------------
    def test_revalue_existing_entries_and_archive(self):
        day = timezone.localdate()
        entry = dm.TimesheetEntry.objects.create(user=self.dev, workspace=self.ws, project=self.project,
                                                 entry_date=day, hours=Decimal("8"), description="API")
        self.assertEqual(entry.cost_snapshot.computed_cost, Decimal("0"))  # aucun TJM à la saisie
        self.assertEqual(self.board().json()["summary"]["unvalued_entries"], 1)

        res = self.create(revalue=True)
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()["revalued"]["entries"], 1)
        entry.cost_snapshot.refresh_from_db()
        self.assertEqual(entry.cost_snapshot.computed_cost, Decimal("75000.00"))
        self.assertEqual(self.board().json()["summary"]["unvalued_entries"], 0)

        # Sans revalorisation, une correction de tarif ne touche pas au passé.
        rate = dm.BillingRate.objects.get(user=self.dev)
        res = self.api(self.owner).patch(f"{URL}{rate.pk}/?workspace={self.ws.pk}", {"cost_rate_amount": "60000"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        entry.cost_snapshot.refresh_from_db()
        self.assertEqual(entry.cost_snapshot.computed_cost, Decimal("75000.00"))

        # Archivage : le tarif n'est plus utilisé, revalorisation à la demande.
        res = self.api(self.owner).delete(f"{URL}{rate.pk}/?workspace={self.ws.pk}&revalue=1")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(dm.BillingRate.objects.get(pk=rate.pk).is_archived)
        self.assertEqual(dm.BillingRate.get_user_daily_cost(self.dev), Decimal("0"))
        entry.cost_snapshot.refresh_from_db()
        self.assertEqual(entry.cost_snapshot.computed_cost, Decimal("0"))
        self.assertIsNone(self.member(self.board().json(), self.dev)["current"])


class BillingRateReviewTests(RateFixture):
    """Régressions issues de la relecture : tenant du TJM général, périodes, portée projet, saisies invalides."""

    def rates(self, user=None):
        return [(r.valid_from, r.valid_to, r.cost_rate_amount)
                for r in dm.BillingRate.objects.filter(user=user or self.dev, is_archived=False, project__isnull=True)
                .order_by("valid_from")]

    def test_general_rate_belongs_to_the_home_workspace(self):
        shared = User.objects.create_user("rate-shared", "s@x.test", "pw", first_name="Free", last_name="Lance")
        dm.UserProfile.objects.update_or_create(user=shared, defaults={"workspace": self.other})
        dm.TeamMembership.objects.create(user=shared, workspace=self.ws, team=self.team)  # aussi membre de Pôle Dev
        home_rate = dm.BillingRate.objects.create(user=shared, cost_rate_amount=80000, sale_rate_amount=150000,
                                                  valid_from=date(2026, 1, 1))
        member = self.member(self.board().json(), shared)
        self.assertEqual((member["home"], member["rates"], member["current"]), (False, [], None))
        api = self.api(self.owner)
        self.assertEqual(api.patch(f"{URL}{home_rate.pk}/?workspace={self.ws.pk}", {"cost_rate_amount": "1"},
                                   format="json").status_code, 404)
        self.assertEqual(api.delete(f"{URL}{home_rate.pk}/?workspace={self.ws.pk}").status_code, 404)
        res = self.create(user=shared.pk)
        self.assertEqual((res.status_code, "project" in res.json()), (400, True))
        home_rate.refresh_from_db()
        self.assertEqual((home_rate.valid_to, home_rate.cost_rate_amount, home_rate.is_archived), (None, Decimal("80000.00"), False))
        # Un tarif propre à un projet de cet espace reste possible.
        self.assertEqual(self.create(user=shared.pk, project=self.project.pk).status_code, 201)

    def test_temporary_period_and_undo(self):
        self.create()  # A : 01/01 → ouvert
        self.create(valid_from="2026-06-01", valid_to="2026-06-30", cost_rate_amount="90000", sale_rate_amount="200000")
        self.assertEqual(self.rates(), [(date(2026, 1, 1), date(2026, 5, 31), Decimal("75000.00")),
                                        (date(2026, 6, 1), date(2026, 6, 30), Decimal("90000.00")),
                                        (date(2026, 7, 1), None, Decimal("75000.00"))])
        later = self.create(valid_from="2026-12-01", cost_rate_amount="85000", sale_rate_amount="200000").json()["id"]
        self.assertEqual(self.api(self.owner).delete(f"{URL}{later}/?workspace={self.ws.pk}").status_code, 200)
        self.assertEqual(self.rates()[-1], (date(2026, 7, 1), None, Decimal("75000.00")))  # rouverte, pas de trou

    def test_moving_a_start_date_keeps_periods_contiguous(self):
        self.create()
        second = self.create(valid_from="2026-04-01", cost_rate_amount="80000").json()["id"]
        url = f"{URL}{second}/?workspace={self.ws.pk}"
        self.assertEqual(self.api(self.owner).patch(url, {"valid_from": "2026-05-01"}, format="json").status_code, 200)
        self.assertEqual(self.rates(), [(date(2026, 1, 1), date(2026, 4, 30), Decimal("75000.00")),
                                        (date(2026, 5, 1), None, Decimal("80000.00"))])
        res = self.api(self.owner).patch(url, {"valid_from": "2025-12-15"}, format="json")
        self.assertEqual((res.status_code, "valid_from" in res.json()), (400, True))

    def test_project_rate_stays_on_its_project(self):
        other_project = dm.Project.objects.create(workspace=self.ws, name="CRM", owner=self.owner)
        self.create(cost_rate_amount="50000", sale_rate_amount="150000")
        day = timezone.localdate()
        on_project, elsewhere = (dm.TimesheetEntry.objects.create(user=self.dev, workspace=self.ws, project=p, entry_date=day,
                                                                  hours=Decimal("8"), description="x")
                                 for p in (self.project, other_project))
        res = self.create(project=self.project.pk, cost_rate_amount="90000", sale_rate_amount="250000", revalue=True)
        self.assertEqual(res.json()["revalued"]["entries"], 1)
        on_project.cost_snapshot.refresh_from_db()
        elsewhere.cost_snapshot.refresh_from_db()
        self.assertEqual((on_project.cost_snapshot.computed_cost, elsewhere.cost_snapshot.computed_cost),
                         (Decimal("90000.00"), Decimal("50000.00")))
        self.assertEqual(dm.BillingRate.get_user_sale_daily_rate(self.dev), Decimal("150000.00"))  # général
        self.assertEqual(dm.BillingRate.get_user_sale_daily_rate(self.dev, project=other_project), Decimal("150000.00"))

    def test_invalid_input_is_a_400(self):
        res = self.create(cost_rate_amount="NaN")
        self.assertEqual((res.status_code, "cost_rate_amount" in res.json()), (400, True))
        self.assertEqual(self.api(self.owner).get(URL, {"workspace": "²"}).status_code, 400)
        res = self.api(self.owner).post(f"{URL}?workspace={self.ws.pk}", [1, 2], format="json")
        self.assertEqual(res.status_code, 400)
        res = self.create(currency=5)
        self.assertEqual(res.status_code, 201)
