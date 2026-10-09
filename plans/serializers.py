from rest_framework import serializers

from .models import Plan


class PlanSerializer(serializers.ModelSerializer):
    provider = serializers.PrimaryKeyRelatedField(read_only=True)
    provider_email = serializers.EmailField(source="provider.email", read_only=True)

    class Meta:
        model = Plan
        fields = (
            "id", "name", "description", "price", "currency", "billing_interval",
            "is_active", "provider", "provider_email", "created_at", "updated_at",
        )
        read_only_fields = ("id", "currency", "provider", "provider_email", "created_at", "updated_at")

    def validate_price(self, value):
        if value <= 0:
            raise serializers.ValidationError("Price must be greater than zero.")
        return value

    def validate_name(self, value):
        user = self.context["request"].user
        qs = Plan.objects.filter(provider=user, name__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("You already have a plan with this name.")
        return value
