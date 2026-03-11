from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import RegisteredUser
import json

# Create your views here.
@csrf_exempt
def register(request):
    if request.method == 'POST':
        # Get the data sent from frontend
        data = json.loads(request.body)
        username = data.get('username')
        email = data.get('email')
        password = data.get('password')

        # Save to MySQL database
        user = RegisteredUser.objects.create(
            username=username,
            email=email,
            password=password
        )

        # Send back a response to her frontend
        return JsonResponse({
            'message': 'User registered successfully!',
            'username': username,
            'email': email,
            'id': user.id
        }, status=201)

    # If someone tries to access this URL without POST
    return JsonResponse({'message': 'Method not allowed'}, status=405)