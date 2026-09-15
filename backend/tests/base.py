from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APITestCase


class BaseAPITestCase(APITestCase):
    """Every test starts with a clean cache so throttle counters and cached
    settings/hotel content never leak between tests.

    EMAIL_EAGER_INLINE makes eager (in-process) email delivery deterministic:
    queue_email dispatches in the calling thread instead of a background
    daemon thread, so assertions about EmailLog status are never racy.
    """

    def setUp(self):
        cache.clear()
        with override_settings(EMAIL_EAGER_INLINE=True):
            self._email_inline = override_settings(EMAIL_EAGER_INLINE=True)
            self._email_inline.enable()
        super().setUp()

    def tearDown(self):
        self._email_inline.disable()
        cache.clear()
        super().tearDown()

    def auth(self, user):
        self.client.force_authenticate(user=user)

    def unauth(self):
        self.client.force_authenticate(user=None)
