from rest_framework import serializers

EVENT_SUCCESS = "payment.success"
EVENT_FAILED = "payment.failed"


class WebhookSerializer(serializers.Serializer):
    event = serializers.ChoiceField(choices=[EVENT_SUCCESS, EVENT_FAILED])
    reference = serializers.CharField(max_length=64)
    provider_reference = serializers.CharField(max_length=128)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0)
    currency = serializers.CharField(max_length=3, required=False)
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True)
