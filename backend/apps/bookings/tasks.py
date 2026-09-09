"""Celery tasks for the bookings app."""
import logging

from celery import shared_task

logger = logging.getLogger("apps")


@shared_task(name="apps.bookings.tasks.expire_pending_bookings")
def expire_pending_bookings():
    """Scheduled every 5 minutes: release inventory held by abandoned bookings."""
    from .services.booking_service import expire_stale_pending_bookings

    count = expire_stale_pending_bookings()
    if count:
        logger.info("Expired %s stale pending booking(s).", count)
    return count
