from django.contrib import admin

from .models import Offer


@admin.register(Offer)
class OfferAdmin(admin.ModelAdmin):
    list_display = ("title", "discount_type", "discount_value", "start_date", "end_date", "is_active", "is_featured")
    list_filter = ("is_active", "is_featured", "discount_type")
    prepopulated_fields = {"slug": ("title",)}
    filter_horizontal = ("room_types",)
