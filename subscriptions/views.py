from django.db.models import Prefetch
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.permissions import IsCustomer
from payments.models import Payment

from . import services
from .filters import SubscriptionFilter
from .models import Subscription
from .serializers import (
    SubscriptionCreatedResponseSerializer,
    SubscriptionCreateSerializer,
    SubscriptionSerializer,
)


class SubscriptionViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """
    POST /api/subscriptions/              customer subscribes -> PENDING + payment reference
    GET  /api/subscriptions/?status=ACTIVE&page=2
    GET  /api/subscriptions/{id}/
    POST /api/subscriptions/{id}/cancel/

    Visibility: customers see their own; providers see subscriptions to their
    plans (= their customers); admins see everything.
    """

    serializer_class = SubscriptionSerializer
    filterset_class = SubscriptionFilter
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        if self.action == "create":
            return [IsAuthenticated(), IsCustomer()]
        return super().get_permissions()

    def get_queryset(self):
        user = self.request.user
        # select_related: customer, plan and provider come in the SAME query (JOIN).
        # prefetch_related: all payments for the page in ONE extra query.
        # => 2 queries for a page, no matter how many rows (+1 for COUNT).
        qs = Subscription.objects.select_related("customer", "plan", "plan__provider").prefetch_related(
            Prefetch("payments", queryset=Payment.objects.order_by("-created_at"))
        )
        if user.is_admin_role:
            return qs
        if user.is_provider:
            return qs.filter(plan__provider=user)
        return qs.filter(customer=user)

    @extend_schema(request=SubscriptionCreateSerializer, responses={201: SubscriptionCreatedResponseSerializer})
    def create(self, request):
        serializer = SubscriptionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = services.create_subscription(customer=request.user, plan_id=serializer.validated_data["plan_id"])
        sub, payment = result["subscription"], result["payment"]
        body = {
            "subscription_id": sub.id,
            "payment_reference": payment.reference,
            "amount": str(payment.amount),
            "currency": payment.currency,
            "status": sub.status,
        }
        return Response(body, status=status.HTTP_201_CREATED if result["created"] else status.HTTP_200_OK)

    @extend_schema(request=None, responses={200: SubscriptionSerializer})
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        sub = services.cancel_subscription(subscription_id=pk, user=request.user)
        sub = self.get_queryset().get(pk=sub.pk)
        return Response(SubscriptionSerializer(sub).data)
