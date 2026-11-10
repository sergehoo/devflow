"""Board de sprint (statut) et décalage de roadmap : RBAC sprint.edit / roadmap.edit, isolation, ancienne URL comprise."""

import json
from datetime import date

from project import models as dm
from project.tests_api_raw_writes import RawApiFixture


class AgileRightsTests(RawApiFixture):
    def setUp(self):
        super().setUp()
        self.roadmap = dm.Roadmap.objects.create(workspace=self.ws, name="R1", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))
        self.item = dm.RoadmapItem.objects.create(roadmap=self.roadmap, title="Lot 1", start_date=date(2026, 3, 1), end_date=date(2026, 3, 31))
        self.foreign_sprint = dm.Sprint.objects.create(workspace=self.other, project=self.foreign_project, name="X",
                                                       start_date=date(2026, 1, 1), end_date=date(2026, 1, 14))

    def post(self, user, url, body):
        return self.api(user).post(url, body, format="json")

    def test_sprint_status_requires_sprint_edit_everywhere(self):
        url = f"/api/v1/sprints/{self.sprint2.pk}/status/"
        self.assertEqual(self.post(self.dev, url, {"status": "ACTIVE"}).status_code, 403)
        self.client.force_login(self.dev)
        legacy = self.client.post("/sprints/status/update/", json.dumps({"sprint_id": self.sprint2.pk, "status": "ACTIVE"}), content_type="application/json")
        self.assertEqual(legacy.status_code, 403)
        self.sprint2.refresh_from_db()
        self.assertNotEqual(self.sprint2.status, "ACTIVE")
        res = self.post(self.pm, url, {"status": "ACTIVE"})
        self.assertEqual((res.status_code, res.json()["status"]), (200, "ACTIVE"))
        self.assertEqual(self.post(self.pm, url, {"status": "NOPE"}).status_code, 400)
        self.assertEqual(self.post(self.pm, f"/api/v1/sprints/{self.foreign_sprint.pk}/status/", {"status": "DONE"}).status_code, 404)

    def test_roadmap_shift_requires_roadmap_edit_and_stays_in_period(self):
        url = f"/api/v1/roadmap-items/{self.item.pk}/shift-dates/"
        self.assertEqual(self.post(self.dev, url, {"delta_days": 7}).status_code, 403)
        res = self.post(self.owner, url, {"delta_days": 7})
        self.assertEqual((res.status_code, res.json()["start_date"]), (200, "2026-03-08"))
        self.assertEqual(self.post(self.owner, url, {"delta_days": 400}).status_code, 400)
