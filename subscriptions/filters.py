import django_filters

from .models import Subscription


class SubscriptionFilter(django_filters.FilterSet):
    status = django_filters.ChoiceFilter(choices=Subscription.Status.choices)
    plan = django_filters.NumberFilter(field_name="plan_id")
    created_after = django_filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="gte")
    created_before = django_filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="lte")

    class Meta:
        model = Subscription
        fields = ["status", "plan", "created_after", "created_before"]
