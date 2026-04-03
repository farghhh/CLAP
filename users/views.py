from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from .models import Profile
from django.core.mail import send_mail
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.conf import settings

def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }

#register user function
@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    name = request.data.get('name')
    email = request.data.get('email')
    password = request.data.get('password')

    if not name or not email or not password:
        return Response(
            {'error': 'All fields are required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if User.objects.filter(email=email).exists():
        return Response(
            {'error': 'Email already registered'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if User.objects.filter(username=name).exists():
        return Response(
            {'error': 'Username already taken'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Create user using Django's built in method
    # This automatically encrypts the password
    user = User.objects.create_user(
        username=name,
        email=email,
        password=password
    )

    # Create profile for this user
    Profile.objects.create(user=user)

    tokens = get_tokens_for_user(user)

    return Response({
        'access': tokens['access'],
        'refresh': tokens['refresh'],
        'user': {
            'name': user.username,
            'email': user.email,
            'onboarding_complete': user.profile.onboarding_complete,
        }
    }, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([AllowAny])
def login(request):
    email = request.data.get('email')
    password = request.data.get('password')

    if not email or not password:
        return Response(
            {'error': 'Email and password are required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Find user by email first
    try:
        user_obj = User.objects.get(email=email)
    except User.DoesNotExist:
        return Response(
            {'error': 'Invalid email or password'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    # Then verify password using Django's built in method
    user = authenticate(username=user_obj.username, password=password)
    if not user:
        return Response(
            {'error': 'Invalid email or password'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    tokens = get_tokens_for_user(user)

    return Response({
        'access': tokens['access'],
        'refresh': tokens['refresh'],
        'user': {
            'name': user.username,
            'email': user.email,
            'onboarding_complete': user.profile.onboarding_complete,
        }
    }, status=status.HTTP_200_OK)


#forgot password function
@api_view(['POST'])
@permission_classes([AllowAny])
def forgot_password(request):
    email = request.data.get('email')

    if not email:
        return Response(
            {'error': 'Email is required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Always return success even if email doesn't exist
    # This prevents attackers from knowing which emails are registered
    try:
        user = User.objects.get(email=email)

        # Generate reset token
        token = default_token_generator.make_token(user)
        uid = urlsafe_base64_encode(force_bytes(user.pk))

        # Build reset link
        reset_link = f"{settings.FRONTEND_URL}/reset-password.html?uid={uid}&token={token}"

        # Send email
        send_mail(
            subject='Reset Your CLAP Password',
            message=f'''
Hi {user.username},

You requested to reset your CLAP password.

Click the link below to reset your password:
{reset_link}

This link will expire in 24 hours.

If you did not request this, please ignore this email.

CLAP Team
            ''',
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=[email],
            fail_silently=False,
        )

    except User.DoesNotExist:
        pass  # Silently ignore if email doesn't exist

    # Always return success
    return Response({
        'message': 'If an account exists for this email, a reset link has been sent.'
    }, status=status.HTTP_200_OK)


#reset password function
@api_view(['POST'])
@permission_classes([AllowAny])
def reset_password(request):
    uid = request.data.get('uid')
    token = request.data.get('token')
    new_password1 = request.data.get('new_password1')
    new_password2 = request.data.get('new_password2') 

    if not all([uid, token, new_password1, new_password2]):
        return Response(
            {'error': 'All fields are required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Check passwords match
    if new_password1 != new_password2:
        return Response(
            {'error': 'Passwords do not match'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        user_id = force_str(urlsafe_base64_decode(uid))
        user = User.objects.get(pk=user_id)
    except (User.DoesNotExist, ValueError, TypeError):
        return Response(
            {'error': 'Invalid reset link'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not default_token_generator.check_token(user, token):
        return Response(
            {'error': 'Reset link has expired or is invalid'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Set new password
    user.set_password(new_password1)
    user.save()

    return Response({
        'message': 'Password reset successfully!'
    }, status=status.HTTP_200_OK)

#change email and password function
@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated])
def profile(request):
    user = request.user

    #return profile info
    if request.method == 'GET':
        return Response({
            'name': user.username,
            'email': user.email,
            'onboarding_complete': user.profile.onboarding_complete,
        }, status=status.HTTP_200_OK)

    #update profile info
    if request.method == 'PUT':
        name = request.data.get('name', user.username)
        email = request.data.get('email', user.email)

        #check if new email is taken by another user
        if email != user.email and User.objects.filter(email=email).exists():
            return Response(
                {'error': 'Email already in use'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check if new name is taken by another user
        if name != user.username and User.objects.filter(username=name).exists():
            return Response(
                {'error': 'Username already taken'},
                status=status.HTTP_400_BAD_REQUEST
            )

        user.username = name
        user.email = email
        user.save()

        return Response({
            'message': 'Profile updated successfully!',
            'name': user.username,
            'email': user.email,
        }, status=status.HTTP_200_OK)


#change password function
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def change_password(request):
    user = request.user
    old_password = request.data.get('old_password')
    new_password1 = request.data.get('new_password1')
    new_password2 = request.data.get('new_password2')

    if not all([old_password, new_password1, new_password2]):
        return Response(
            {'error': 'All fields are required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    #verify old password
    if not user.check_password(old_password):
        return Response(
            {'error': 'Current password is incorrect'},
            status=status.HTTP_400_BAD_REQUEST
        )

    #check new passwords match
    if new_password1 != new_password2:
        return Response(
            {'error': 'New passwords do not match'},
            status=status.HTTP_400_BAD_REQUEST
        )

    #check new password is different
    if old_password == new_password1:
        return Response(
            {'error': 'New password must be different from current password'},
            status=status.HTTP_400_BAD_REQUEST
        )

    user.set_password(new_password1)
    user.save()

    return Response({
        'message': 'Password changed successfully!'
    }, status=status.HTTP_200_OK)