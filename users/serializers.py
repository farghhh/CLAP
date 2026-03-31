from rest_framework import serializers
from .models import User
import hashlib

#for data validation, ensuring that it's provided (for registration)
class RegisterSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['username', 'email', 'password']

    def create(self, validated_data):
        # Encrypt password before saving
        validated_data['password'] = hashlib.sha256(
            validated_data['password'].encode()
        ).hexdigest()
        return super().create(validated_data)

#for data validation, ensuring that it's provided (for login)
class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField()