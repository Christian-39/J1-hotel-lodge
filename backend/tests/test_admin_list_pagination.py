"""Admin list pagination pins (DRF StandardPagination reused as-is).

Covers the endpoints the staff console paginates client-side:
GET /api/admin/bookings/, /api/admin/payments/, /api/admin/audit-logs/,
/api/admin/guests/ (+ refunds + users on the same base class).

For each: page boundaries (rows split across pages with no overlap or
duplication), the count/page_size/total_pages contract, server-side filter +
search preserving pagination, and the page_size cap (200 asked -> 100 max).
Receipts read the /api/admin/payments/?status=SUCCESS endpoint, so paginating
payments paginates receipts too (verified here against status=SUCCESS).
"""
from datetime import timedelta

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.bookings.models import Booking, Guest
from apps.core.utils import hotel_today
from apps.payments.models import Payment

from .base import BaseAPITestCase
from .factories import make_booking, make_guest, make_room, make_room_type


class PageContractMixin:
    """Shared assertions for every paginated admin list."""

    @staticmethod
    def pagination(res):
        return res.json().get("pagination") or {}

    def assert_contract_shape(self, res):
        pg = self.pagination(res)
        for key in ("count", "page", "page_size", "total_pages", "next", "previous"):
            assert key in pg, f"pagination block is missing {key!r}: {pg}"
        return pg

    def assert_first_page(self, res, *, expected_rows, expected_count):
        self.assertEqual(res.status_code, 200, res.json())
        pg = self.assert_contract_shape(res)
        rows = res.json()["data"]
        self.assertEqual(len(rows), expected_rows)
        self.assertEqual(pg["count"], expected_count)
        self.assertEqual(pg["page"], 1)
        self.assertEqual(pg["page_size"], 20)
        self.assertEqual(pg["total_pages"], max(1, -(-expected_count // 20)) if expected_count else 1)
        self.assertIsNone(pg["previous"])
        self.assertEqual(bool(pg["next"]), expected_count > 20)
        return rows

    def assert_second_page(self, res, *, expected_rows, expected_count):
        self.assertEqual(res.status_code, 200, res.json())
        pg = self.assert_contract_shape(res)
        rows = res.json()["data"]
        self.assertEqual(len(rows), expected_rows)
        self.assertEqual(pg["page"], 2)
        self.assertEqual(pg["count"], expected_count)
        self.assertIsNotNone(pg["previous"])
        self.assertIsNone(pg["next"])
        return rows


class AdminBookingPaginationTests(PageContractMixin, BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.staff = User.objects.create_user(
            email="pager-desk@staff.dev", password="Passw0rd!234",
            first_name="Desk", last_name="Pager", role=User.Role.RECEPTIONIST,
        )
        self.auth(self.staff)
        self.room_type = make_room_type("Pager Deluxe", price="25000.00")
        make_room(self.room_type, "PD1")
        self.guest = make_guest("pager-guest@test.dev")
        today = hotel_today()
        # 25 bookings so the default 20-row window spills to a second page.
        for i in range(25):
            make_booking(
                self.guest, self.room_type,
                check_in=today + timedelta(days=10 + i),
                check_out=today + timedelta(days=11 + i),
            )

    def get(self, **params):
        return self.client.get("/api/admin/bookings/", params)

    def test_default_page_one_and_two_split_without_overlap(self):
        page1 = self.assert_first_page(self.get(), expected_rows=20, expected_count=25)
        page2 = self.assert_second_page(self.get(page=2), expected_rows=5, expected_count=25)
        ids1 = {row["id"] for row in page1}
        ids2 = {row["id"] for row in page2}
        self.assertFalse(ids1 & ids2, "pages must not overlap")
        self.assertEqual(len(ids1 | ids2), 25)

    def test_total_pages_next_previous_contract(self):
        pg = self.assert_contract_shape(self.get())
        self.assertEqual(pg["total_pages"], 2)
        self.assertEqual(pg["page"], 1)
        assert "page=2" in pg["next"]
        pg2 = self.assert_contract_shape(self.get(page=2))
        # DRF links back to page 1 without an explicit ?page=1 parameter.
        assert pg2["previous"] and "page=" not in pg2["previous"]

    def test_status_filter_paginates_the_filtered_set(self):
        # First page of unpaid pending holds.
        res = self.get(status="PENDING")
        pg = self.assert_contract_shape(res)
        self.assertEqual(pg["count"], 0)
        self.assertEqual(res.json()["data"], [])
        # Turn 7 rows into pending and re-check pagination of the filtered set.
        for b in Booking.objects.all()[:7]:
            b.status = Booking.Status.PENDING
            b.save(update_fields=["status"])
        res = self.get(status="PENDING")
        rows = self.assert_first_page(res, expected_rows=7, expected_count=7)
        assert {row["status"] for row in rows} == {"PENDING"}
        # The filtered set fits on one page: asking for page 2 is a graceful
        # 404 (DRF behaviour — never a 500, never fabricated rows).
        self.assertEqual(self.get(status="PENDING", page=2).status_code, 404)

    def test_search_paginates_the_matched_set(self):
        res = self.get(search=self.guest.email)
        self.assert_first_page(res, expected_rows=20, expected_count=25)
        res = self.get(search=self.guest.email, page=2)
        self.assert_second_page(res, expected_rows=5, expected_count=25)

    def test_ordering_is_honoured_within_pages(self):
        res = self.get(ordering="check_in")
        rows = self.assert_first_page(res, expected_rows=20, expected_count=25)
        checkins = [row["check_in"] for row in rows]
        self.assertEqual(checkins, sorted(checkins))

    def test_page_size_is_capped_at_100(self):
        res = self.get(page_size=200)
        pg = self.assert_contract_shape(res)
        self.assertEqual(pg["page_size"], 100)
        res = self.get(page_size=5)
        pg = self.assert_contract_shape(res)
        self.assertEqual(pg["page_size"], 5)
        self.assertEqual(len(res.json()["data"]), 5)

    def test_out_of_range_last_page_is_404_not_500(self):
        res = self.get(page=99)
        self.assertEqual(res.status_code, 404)
        # The response stays a parseable JSON envelope error.
        body = res.json()
        self.assertTrue(isinstance(body, dict))


class AdminPaymentPaginationTests(PageContractMixin, BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.staff = User.objects.create_user(
            email="pager-pay@staff.dev", password="Passw0rd!234",
            first_name="Pay", last_name="Pager", role=User.Role.RECEPTIONIST,
        )
        self.auth(self.staff)
        self.room_type = make_room_type("PayPager", price="30000.00")
        make_room(self.room_type, "PP1")
        self.guest = make_guest("pager-pay-guest@test.dev")
        self.booking = make_booking(self.guest, self.room_type)
        for i in range(25):
            Payment.objects.create(
                booking=self.booking, user=self.staff,
                reference=f"J1P-PAGE-{i:03d}",
                provider=Payment.Provider.CASH if i % 2 else Payment.Provider.POS,
                amount="30000.00", currency="NGN",
                status=Payment.Status.SUCCESS if i % 3 else Payment.Status.PENDING,
            )

    def get(self, **params):
        return self.client.get("/api/admin/payments/", params)

    def test_default_page_one_and_two_split(self):
        page1 = self.assert_first_page(self.get(), expected_rows=20, expected_count=25)
        page2 = self.assert_second_page(self.get(page=2), expected_rows=5, expected_count=25)
        self.assertFalse({r["id"] for r in page1} & {r["id"] for r in page2})

    def test_receipts_query_status_success_paginates(self):
        # The receipts console IS this endpoint filtered by status=SUCCESS.
        res = self.get(status="SUCCESS")
        pg = self.assert_contract_shape(res)
        rows = res.json()["data"]
        self.assertEqual(pg["count"], Payment.objects.filter(status=Payment.Status.SUCCESS).count())
        for row in rows:
            self.assertEqual(row["status"], "SUCCESS")

    def test_provider_filter_paginates(self):
        res = self.get(provider="CASH")
        pg = self.assert_contract_shape(res)
        self.assertEqual(pg["count"], Payment.objects.filter(provider="CASH").count())
        for row in res.json()["data"]:
            self.assertEqual(row["provider"], "CASH")

    def test_search_paginates_the_matched_set(self):
        # All 25 payments match the guest's email (join search).
        res = self.get(search=self.guest.email)
        pg = self.assert_contract_shape(res)
        self.assertEqual(pg["count"], 25)
        self.assertEqual(pg["total_pages"], 2)
        page2 = self.assert_second_page(self.get(search=self.guest.email, page=2),
                                        expected_rows=5, expected_count=25)
        self.assertFalse({r["id"] for r in res.json()["data"]} & {r["id"] for r in page2})
        # An exact reference search selects exactly this row.
        res = self.get(search="J1P-PAGE-007")
        pg = self.assert_contract_shape(res)
        self.assertEqual(pg["count"], 1)
        self.assertEqual(res.json()["data"][0]["reference"], "J1P-PAGE-007")


class AdminAuditLogPaginationTests(PageContractMixin, BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_user(
            email="pager-admin@staff.dev", password="Passw0rd!234",
            first_name="Audit", last_name="Admin", role=User.Role.ADMIN,
        )
        self.auth(self.admin)
        today = hotel_today()
        for i in range(25):
            AuditLog.objects.create(
                actor=self.admin, action="SETTINGS_CHANGED",
                object_type="HotelSettings", object_id="1",
                summary=f"pager sweep {i:02d} {today:%Y-%m-%d}",
            )

    def get(self, **params):
        return self.client.get("/api/admin/audit-logs/", params)

    def test_default_page_one_and_two_split(self):
        page1 = self.assert_first_page(self.get(), expected_rows=20, expected_count=25)
        page2 = self.assert_second_page(self.get(page=2), expected_rows=5, expected_count=25)
        self.assertFalse({r["id"] for r in page1} & {r["id"] for r in page2})

    def test_action_filter_paginates(self):
        AuditLog.objects.create(actor=self.admin, action="USER_CREATED", object_type="User", object_id="9")
        res = self.get(action="USER_CREATED")
        pg = self.assert_contract_shape(res)
        self.assertEqual(pg["count"], 1)
        self.assertEqual(res.json()["data"][0]["action"], "USER_CREATED")

    def test_date_filter_paginates(self):
        today = hotel_today().isoformat()
        res = self.get(date_from=today, date_to=today)
        pg = self.assert_contract_shape(res)
        self.assertEqual(pg["count"], 25)


class AdminGuestPaginationTests(PageContractMixin, BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.staff = User.objects.create_user(
            email="pager-guests@staff.dev", password="Passw0rd!234",
            first_name="Guest", last_name="Pager", role=User.Role.RECEPTIONIST,
        )
        self.auth(self.staff)
        for i in range(25):
            make_guest(f"pager-g{i:02d}@test.dev", first_name=f"Pager{i:02d}", last_name="Obi")

    def get(self, **params):
        return self.client.get("/api/admin/guests/", params)

    def test_default_page_one_and_two_split(self):
        page1 = self.assert_first_page(self.get(), expected_rows=20, expected_count=Guest.objects.count())
        page2 = self.assert_second_page(self.get(page=2), expected_rows=Guest.objects.count() - 20,
                                        expected_count=Guest.objects.count())
        self.assertFalse({r["id"] for r in page1} & {r["id"] for r in page2})

    def test_search_paginates_the_matched_set(self):
        res = self.get(search="pager-g0")
        pg = self.assert_contract_shape(res)
        self.assertEqual(pg["count"], 10)   # pager-g00 .. pager-g09
        res = self.get(search="obi")
        pg = self.assert_contract_shape(res)
        self.assertEqual(pg["count"], 25)
