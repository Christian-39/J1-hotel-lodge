from django.core.cache import cache
from rest_framework.test import APITestCase


class BaseAPITestCase(APITestCase):
    """Every test starts with a clean cache so throttle counters and cached
    settings/hotel content never leak between tests."""

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
