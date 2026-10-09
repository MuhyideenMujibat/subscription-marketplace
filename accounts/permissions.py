from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsCustomer(BasePermission):
    message = "Only customers can perform this action."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_customer)


class IsProvider(BasePermission):
    message = "Only providers can perform this action."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_provider)


class IsPlanOwnerOrReadOnly(BasePermission):
    message = "You can only modify your own plans."

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        return obj.provider_id == request.user.id
