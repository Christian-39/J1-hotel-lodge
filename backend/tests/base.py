from django.core.cache import cache

from rest_framework.test import APITestCase

class BaseAPITestCase(APITestCase):
    """Every test starts with a clean cache so throttle counters and cached
    settings/hotel content never leak between tests.

    Email delivery is synchronous and in-process now (no Celery, no broker):
    Django's locmem email backend captures messages in ``mail.outbox`` and the
    EmailLog row is final by the time the request/handlr returns, so status
    assertions are deterministic by construction.
    """

    def setUp(self):
        cache.clear()
        super().setUp()

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def auth(self, user):
        self.client.force_authenticate(user=user)

    def unauth(self):
        self.client.force_authenticate(user=None)
