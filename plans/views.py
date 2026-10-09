from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError, Q
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from accounts.permissions import IsPlanOwnerOrReadOnly, IsProvider
from core.exceptions import Conflict

from .cache import get_cached_list, set_cached_list
from .models import Plan
from .serializers import PlanSerializer


class PlanViewSet(viewsets.ModelViewSet):
    """
    GET    /api/plans/            public, cached list of active plans
    GET    /api/plans/?mine=true  provider: own plans (incl. inactive), not cached
    POST   /api/plans/            provider only
    GET    /api/plans/{id}/
    PATCH  /api/plans/{id}/       owner only
    DELETE /api/plans/{id}/       owner only
    """

    serializer_class = PlanSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [AllowAny()]
        if self.action == "create":
            return [IsAuthenticated(), IsProvider()]
        return [IsAuthenticated(), IsProvider(), IsPlanOwnerOrReadOnly()]

    def _wants_own_plans(self):
        user = self.request.user
        return (
            self.request.query_params.get("mine") in ("1", "true")
            and user.is_authenticated
            and user.is_provider
        )

    def get_queryset(self):
        qs = Plan.objects.select_related("provider")
        user = self.request.user
        if self.action == "list":
            if self._wants_own_plans():
                return qs.filter(provider=user)
            return qs.filter(is_active=True)
        if self.action == "retrieve":
            # Anyone can see active plans; a provider can also see their own inactive ones.
            if user.is_authenticated and user.is_provider:
                return qs.filter(Q(is_active=True) | Q(provider=user))
            return qs.filter(is_active=True)
        # update / delete: look up every plan so a non-owner gets 403 (not 404).
        return qs

    @extend_schema(parameters=[OpenApiParameter("mine", bool, description="Provider: list only my plans")])
    def list(self, request, *args, **kwargs):
        if self._wants_own_plans():
            return super().list(request, *args, **kwargs)

        query_string = request.META.get("QUERY_STRING", "")
        cached = get_cached_list(query_string)
        if cached is not None:
            response = Response(cached)
            response["X-Cache"] = "HIT"
            return response

        response = super().list(request, *args, **kwargs)
        if response.status_code == 200:
            set_cached_list(query_string, response.data)
        response["X-Cache"] = "MISS"
        return response

    def perform_create(self, serializer):
        try:
            serializer.save(provider=self.request.user, currency=settings.PAYMENT_CURRENCY)
        except IntegrityError:
            raise Conflict("You already have a plan with this name.", code="duplicate_plan_name")

    def perform_update(self, serializer):
        # Lock the plan row while updating. Subscription creation also locks this
        # row, so "deactivate plan" and "subscribe to plan" can never interleave.
        with transaction.atomic():
            Plan.objects.select_for_update().get(pk=serializer.instance.pk)
            serializer.save()

    def perform_destroy(self, instance):
        try:
            instance.delete()
        except ProtectedError:
            raise Conflict(
                "This plan has subscriptions and cannot be deleted. Deactivate it instead (PATCH is_active=false).",
                code="plan_has_subscriptions",
            )
