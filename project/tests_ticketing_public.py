"""
Collecte sans API : formulaire existant (SDK), widget, formulaire public hébergé.

    DJANGO_SETTINGS_MODULE=ProjectFlow.settings.test python manage.py test project.tests_ticketing_public
"""
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile

from project import models as dm
from project.services import ticketing as svc
from project.services import ticketing_public as tp
from project.tests_ticketing import PNG, TicketingFixture

ORIGIN = "https://app.client.test"


class PublicIntakeTests(TicketingFixture):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(tp, "TOKEN_MIN_AGE", 0)  # délai anti-robot testé à part
        patcher.start()
        self.addCleanup(patcher.stop)

    def configure(self, user=None, **payload):
        payload = payload or {"modes": {"form": True, "widget": True, "hosted": True}, "allowed_origins": [ORIGIN, "https://app.client.test/"]}
        return self.api(user or self.owner).patch(f"/api/v1/ticket-applications/{self.app.pk}/collection/", payload,
                                                  content_type="application/json")

    def enabled(self):
        data = self.configure().json()
        self.app.refresh_from_db()
        return data

    def token(self, mode="hosted", origin=""):
        headers = {"HTTP_ORIGIN": origin} if origin else {}
        return self.client.get(f"/api/v1/public/apps/{self.app.public_key}/", {"mode": mode}, **headers)

    def submit(self, mode="hosted", origin="", ip="198.51.100.20", **fields):
        data = {"mode": mode, "form_token": self.token(mode, origin).json().get("form_token", ""), "title": "Écran de paiement figé",
                "description": "Le bouton reste grisé.", "email": "client@acme.test", "name": "Client Acme", **fields}
        headers = {"REMOTE_ADDR": ip, **({"HTTP_ORIGIN": origin} if origin else {})}
        return self.client.post(f"/api/v1/public/apps/{self.app.public_key}/tickets/", data, **headers)

    def test_configuration_is_admin_only_and_validated(self):
        self.assertEqual(self.configure(user=self.pm).status_code, 403)  # pas ticket.admin
        self.assertEqual(self.configure(user=self.bob).status_code, 404)  # autre workspace
        bad = self.configure(allowed_origins=["javascript:alert(1)"])
        self.assertEqual(bad.status_code, 400)
        data = self.enabled()
        self.assertTrue(data["public_key"].startswith("dfp_"))
        self.assertEqual(data["allowed_origins"], [ORIGIN])
        self.assertEqual(data["hosted_path"], f"/support/app/{self.app.public_slug}/")
        self.assertNotIn(self.secret, str(data))  # le secret HMAC n'est jamais renvoyé
        test = self.api(self.owner).post(f"/api/v1/ticket-applications/{self.app.pk}/collection/test/", {"mode": "form"},
                                         content_type="application/json").json()
        self.assertTrue(test["ok"], test)
        old = data["public_key"]
        rotated = self.api(self.owner).post(f"/api/v1/ticket-applications/{self.app.pk}/collection/rotate-key/").json()
        self.assertNotEqual(rotated["public_key"], old)
        self.assertEqual(self.client.get(f"/api/v1/public/apps/{old}/", {"mode": "hosted"}).status_code, 404)

    def test_hosted_form_page_and_submission(self):
        self.assertEqual(self.client.get("/support/app/inconnue/").status_code, 404)
        self.enabled()
        page = self.client.get(f"/support/app/{self.app.public_slug}/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("frame-ancestors 'self'", page["Content-Security-Policy"])
        self.assertContains(page, "Signaler un problème")
        self.assertNotContains(page, self.secret)
        embed = self.client.get(f"/support/app/{self.app.public_slug}/", {"embed": "1", "origin": ORIGIN})
        self.assertIn(f"frame-ancestors {ORIGIN}", embed["Content-Security-Policy"])

        res = self.submit()
        self.assertEqual(res.status_code, 201, res.content)
        body = res.json()
        ticket = dm.Ticket.objects.get(reference=body["reference"], workspace=self.ws)
        self.assertEqual((ticket.application, ticket.source, ticket.reporter_email), (self.app, "PORTAL", "client@acme.test"))
        self.assertTrue(body["tracking_code"])
        self.assertNotIn(body["tracking_code"], ticket.public_token_hash)
        self.assertTrue(ticket.events.filter(action="created", origin="PUBLIC").exists())

        no_mail = self.submit(email="", title="Autre problème constaté")
        self.assertEqual(no_mail.status_code, 400)  # e-mail obligatoire sur le formulaire public

    def test_token_honeypot_replay_and_speed(self):
        self.enabled()
        token = self.token().json()["form_token"]
        url = f"/api/v1/public/apps/{self.app.public_key}/tickets/"
        base = {"mode": "hosted", "title": "Lenteur générale", "email": "a@b.test"}
        self.assertEqual(self.client.post(url, {**base, "form_token": "forge"}).status_code, 400)
        self.assertEqual(self.client.post(url, {**base, "form_token": token, "website": "http://spam"}).status_code, 400)
        self.assertEqual(self.client.post(url, {**base, "form_token": token}).status_code, 201)
        self.assertEqual(self.client.post(url, {**base, "form_token": token, "title": "Autre"}).status_code, 409)  # jeton à usage unique
        with mock.patch.object(tp, "TOKEN_MIN_AGE", 60):
            fast = self.client.post(url, {**base, "form_token": self.token().json()["form_token"], "title": "Trop vite"})
        self.assertEqual(fast.status_code, 400)
        errors = self.api(self.owner).get(f"/api/v1/ticket-applications/{self.app.pk}/collection/").json()["channels"]["hosted"]
        self.assertIn("trop rapide", errors["last_error"]["reason"])

    def test_existing_form_requires_an_allowed_origin(self):
        self.enabled()
        ok = self.token("form", ORIGIN)
        self.assertEqual(ok["Access-Control-Allow-Origin"], ORIGIN)
        denied = self.token("form", "https://evil.test")
        self.assertEqual(denied.status_code, 403)
        self.assertNotIn("Access-Control-Allow-Origin", denied)
        forged = self.client.post(f"/api/v1/public/apps/{self.app.public_key}/tickets/",
                                  {"mode": "form", "form_token": ok.json()["form_token"], "title": "Sans origine"})
        self.assertEqual(forged.status_code, 403)  # sans en-tête Origin autorisé : refus côté serveur
        res = self.submit("form", ORIGIN, email="")
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res["Access-Control-Allow-Origin"], ORIGIN)
        self.assertEqual(dm.Ticket.objects.get(reference=res.json()["reference"], workspace=self.ws).source, "FORM")

    def test_duplicates_and_abusive_submissions(self):
        self.enabled()
        first = self.submit().json()
        again = self.submit()
        self.assertEqual((again.status_code, again.json()["reference"], again.json()["created"]), (200, first["reference"], False))
        self.assertNotIn("tracking_code", again.json())
        for n in range(3):
            self.submit(title=f"Problème numéro {n}")
        self.assertEqual(self.submit(title="Encore un problème").status_code, 429)  # 5 envois / 10 min par IP
        self.assertEqual(self.submit(title="Autre client", ip="198.51.100.99").status_code, 201)

    def test_attachments_are_validated(self):
        self.enabled()
        png = SimpleUploadedFile("capture.png", PNG, content_type="image/png")
        self.assertEqual(self.submit(attachments=[png]).status_code, 201)
        exe = SimpleUploadedFile("outil.exe", b"MZ\x90\x00binaire", content_type="application/octet-stream")
        self.assertEqual(self.submit(title="Pièce jointe refusée", attachments=[exe]).status_code, 400)

    def test_tracking_needs_the_code_and_shows_public_thread_only(self):
        self.enabled()
        created = self.submit().json()
        ticket = dm.Ticket.objects.get(reference=created["reference"], workspace=self.ws)
        svc.add_comment(ticket, body="Correctif en cours.", user=self.pm, visibility="PUBLIC")
        svc.add_comment(ticket, body="Note interne confidentielle", user=self.pm, visibility="INTERNAL")
        url = f"/api/v1/public/apps/{self.app.public_key}/track/"
        self.assertEqual(self.client.post(url, {"reference": created["reference"], "code": "mauvais"}).status_code, 404)
        data = self.client.post(url, {"reference": created["reference"].lower(), "code": created["tracking_code"]}).json()
        self.assertEqual(data["reference"], created["reference"])
        self.assertIn("Correctif en cours.", str(data["messages"]))
        self.assertNotIn("confidentielle", str(data))
        self.assertNotIn("client@acme.test", str(data))
        other, _ = self.make_app(self.other_ws, "beta-form")
        other.collection_modes, other.public_key = {"hosted": True}, tp.new_public_key()
        other.save()
        cross = self.client.post(f"/api/v1/public/apps/{other.public_key}/track/",
                                 {"reference": created["reference"], "code": created["tracking_code"]})
        self.assertEqual(cross.status_code, 404)  # référence d'un autre workspace

    def test_disabled_modes_and_unknown_keys(self):
        self.assertEqual(self.client.get("/api/v1/public/apps/dfp_inconnue/", {"mode": "hosted"}).status_code, 404)
        self.configure(modes={"hosted": True, "widget": False})
        self.app.refresh_from_db()
        self.assertEqual(self.client.get(f"/support/app/{self.app.public_slug}/", {"embed": "1"}).status_code, 404)
        self.assertEqual(self.token("widget").status_code, 404)
        self.app.status = "SUSPENDED"
        self.app.save()
        self.assertEqual(self.client.get(f"/support/app/{self.app.public_slug}/").status_code, 404)
