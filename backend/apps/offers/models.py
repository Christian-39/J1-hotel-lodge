from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.text import slugify

from apps.core.models import TimeStampedModel
from apps.core.validators import validate_image_upload
from apps.rooms.models import RoomType


class Offer(TimeStampedModel):
    class DiscountType(models.TextChoices):
        PERCENTAGE = "PERCENTAGE", "Percentage"
        FIXED_AMOUNT = "FIXED_AMOUNT", "Fixed amount"

    title = models.CharField(max_length=150)
    slug = models.SlugField(max_length=170, unique=True, blank=True)
    description = models.TextField(blank=True, default="")
    short_description = models.CharField(max_length=255, blank=True, default="")
    code = models.CharField(
        max_length=30, unique=True, null=True, blank=True,
        help_text="Optional promo code guests can enter (case-insensitive).",
    )
    discount_type = models.CharField(max_length=20, choices=DiscountType.choices,
                                     default=DiscountType.PERCENTAGE)
    discount_value = models.DecimalField(max_digits=12, decimal_places=2,
                                         validators=[MinValueValidator(Decimal("0.00"))])
    start_date = models.DateField(db_index=True)
    end_date = models.DateField(db_index=True)
    min_nights = models.PositiveSmallIntegerField(default=1)
    max_nights = models.PositiveSmallIntegerField(null=True, blank=True)
    # Empty = applies to every room type.
    room_types = models.ManyToManyField(RoomType, blank=True, related_name="offers")
    is_active = models.BooleanField(default=True, db_index=True)
    is_featured = models.BooleanField(default=False)
    image = models.ImageField(upload_to="offers/%Y/%m/", null=True, blank=True,
                              validators=[validate_image_upload])
    terms = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-is_featured", "-start_date", "title"]
        indexes = [models.Index(fields=["is_active", "start_date", "end_date"])]

    def __str__(self):
        return self.title

    def clean(self):
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "End date cannot be before the start date."})
        if (
            self.discount_type == self.DiscountType.PERCENTAGE
            and self.discount_value is not None
            and self.discount_value > Decimal("100")
        ):
            raise ValidationError({"discount_value": "Percentage discounts cannot exceed 100."})
        if self.max_nights is not None and self.min_nights and self.max_nights < self.min_nights:
            raise ValidationError({"max_nights": "Maximum nights must be >= minimum nights."})

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title) or "offer"
            slug, i = base, 1
            while Offer.objects.exclude(pk=self.pk).filter(slug=slug).exists():
                i += 1
                slug = f"{base}-{i}"
            self.slug = slug
        if self.code:
            self.code = self.code.strip().upper()
        super().save(*args, **kwargs)
