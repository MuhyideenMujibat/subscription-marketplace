from django.contrib.auth import password_validation
from rest_framework import serializers

from .models import User


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "email", "first_name", "last_name", "role", "date_joined")
        # role can never be changed through the API.
        read_only_fields = ("id", "email", "role", "date_joined")


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8, style={"input_type": "password"})
    # Only CUSTOMER or PROVIDER can be chosen at sign-up. ADMIN is never self-assignable.
    role = serializers.ChoiceField(
        choices=[User.Role.CUSTOMER, User.Role.PROVIDER], default=User.Role.CUSTOMER
    )

    class Meta:
        model = User
        fields = ("id", "email", "password", "first_name", "last_name", "role")
        read_only_fields = ("id",)

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def validate(self, attrs):
        password_validation.validate_password(attrs["password"], User(email=attrs.get("email")))
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)
