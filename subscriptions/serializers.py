from rest_framework import serializers

from payments.models import Payment

from .models import Subscription


class SubscriptionCreateSerializer(serializers.Serializer):
    plan_id = serializers.IntegerField(min_value=1)


class SubscriptionCreatedResponseSerializer(serializers.Serializer):
    subscription_id = serializers.IntegerField()
    payment_reference = serializers.CharField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    currency = serializers.CharField()
    status = serializers.CharField()


class PaymentSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ("reference", "amount", "currency", "status", "created_at")


class SubscriptionSerializer(serializers.ModelSerializer):
    customer_email = serializers.EmailField(source="customer.email", read_only=True)
    plan_name = serializers.CharField(source="plan.name", read_only=True)
    plan_price = serializers.DecimalField(source="plan.price", max_digits=12, decimal_places=2, read_only=True)
    billing_interval = serializers.CharField(source="plan.billing_interval", read_only=True)
    provider_id = serializers.IntegerField(source="plan.provider_id", read_only=True)
    payments = PaymentSummarySerializer(many=True, read_only=True)

    class Meta:
        model = Subscription
        fields = (
            "id", "customer", "customer_email", "plan", "plan_name", "plan_price", "billing_interval",
            "provider_id", "status", "start_date", "end_date", "next_billing_date", "cancelled_at",
            "payments", "created_at", "updated_at",
        )
        read_only_fields = fields
