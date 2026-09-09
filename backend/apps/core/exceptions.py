"""Domain exceptions mapped to machine-readable API error codes.

The frontend keys behavior off `code` (see docs/FRONTEND_CONTRACT.md).
"""
from rest_framework import status
from rest_framework.exceptions import APIException


class JOneAPIError(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "The request could not be completed."
    default_code = "ERROR"


class InvalidDatesError(JOneAPIError):
    default_detail = "The selected dates are invalid."
    default_code = "INVALID_DATES"


class CapacityExceededError(JOneAPIError):
    default_detail = "The guest or room count exceeds allowed capacity."
    default_code = "CAPACITY_EXCEEDED"


class RoomUnavailableError(JOneAPIError):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "No rooms of this type are available for the selected dates."
    default_code = "ROOM_UNAVAILABLE"


class BookingExpiredError(JOneAPIError):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "This booking has expired. Please start a new booking."
    default_code = "BOOKING_EXPIRED"


class BookingStateError(JOneAPIError):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "The booking is not in a state that allows this action."
    default_code = "INVALID_BOOKING_STATE"


class CancellationNotAllowedError(JOneAPIError):
    default_detail = "This booking can no longer be cancelled."
    default_code = "CANCELLATION_NOT_ALLOWED"


class OfferNotApplicableError(JOneAPIError):
    default_detail = "This offer cannot be applied to the selected stay."
    default_code = "OFFER_NOT_APPLICABLE"


class PaymentError(JOneAPIError):
    default_detail = "The payment could not be completed."
    default_code = "PAYMENT_FAILED"


class PaymentAlreadyCompletedError(JOneAPIError):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "This booking is already fully paid."
    default_code = "PAYMENT_ALREADY_COMPLETED"


class PaymentAmountMismatchError(JOneAPIError):
    default_detail = "The verified payment amount does not match the expected amount."
    default_code = "PAYMENT_AMOUNT_MISMATCH"


class PaymentNotConfiguredError(JOneAPIError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Online payments are not configured. Please contact the hotel."
    default_code = "PAYMENT_NOT_CONFIGURED"


class PaymentGatewayError(JOneAPIError):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "The payment gateway could not be reached. Please try again."
    default_code = "PAYMENT_GATEWAY_ERROR"


class OutstandingBalanceError(JOneAPIError):
    default_detail = "The booking has an outstanding balance."
    default_code = "OUTSTANDING_BALANCE"
