from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from .models import Task
from schedule.models import StudySession
from sleep.models import SleepStudyPreference
from core.cls_engine import calculate_cls, get_risk_level
from core.schedule_engine import generate_study_sessions, calculate_progress, check_and_redistribute
from datetime import date


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def assignments(request):

    # GET — Return all assignments for this user
    if request.method == 'GET':
        tasks = Task.objects.filter(user=request.user).order_by('-created_at')

        # Difficulty number to string mapping
        diff_display = {1: 'easy', 2: 'medium', 3: 'hard'}

        data = []
        for task in tasks:
            data.append({
                'id': task.task_id,
                'course_code': task.course_code,
                'title': task.title,
                'deadline': str(task.deadline),
                'hours': task.hours,
                'difficulty': diff_display.get(task.difficulty, 'easy'),
                'cls_score': task.cls_score,
                'risk_level': task.risk_level,
                'is_completed': task.is_completed,
                'progress': calculate_progress(task),
            })

        return Response(data, status=status.HTTP_200_OK)

    # POST — Add new assignment
    if request.method == 'POST':
        course_code = request.data.get('course_code')
        title = request.data.get('title')
        deadline = request.data.get('deadline')
        hours = request.data.get('hours')
        difficulty = request.data.get('difficulty')

        # Validate all fields
        if not all([course_code, title, deadline, hours, difficulty]):
            return Response(
                {'error': 'All fields are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Convert string difficulty to integer
        difficulty_map = {'easy': 1, 'medium': 2, 'hard': 3}
        difficulty_int = difficulty_map.get(difficulty.lower())

        if not difficulty_int:
            return Response(
                {'error': 'Invalid difficulty. Must be easy, medium or hard'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Convert deadline string to date
        try:
            deadline_date = date.fromisoformat(deadline)
        except ValueError:
            return Response(
                {'error': 'Invalid deadline format'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check deadline is in the future
        if deadline_date <= date.today():
            return Response(
                {'error': 'Deadline must be in the future'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Calculate CLS score
        cls_score = calculate_cls(difficulty, float(hours), deadline_date)
        risk_level = get_risk_level(cls_score)

        # Create the task
        task = Task.objects.create(
            user=request.user,
            course_code=course_code.upper(),
            title=title,
            deadline=deadline_date,
            hours=float(hours),
            difficulty=difficulty_int,
            cls_score=cls_score,
            risk_level=risk_level,
        )

        # Generate study sessions
        try:
            preference = SleepStudyPreference.objects.get(user=request.user)
            sessions = generate_study_sessions(task, preference)

            for session in sessions:
                StudySession.objects.create(
                    task=task,
                    user=request.user,
                    scheduled_date=session['scheduled_date'],
                    scheduled_hours=session['scheduled_hours'],
                    cls_contribution=session['cls_contribution'],
                )

        except SleepStudyPreference.DoesNotExist:
            pass  # No preferences set yet

        # Check for overload after adding sessions
        recommendation = None
        try:
            preference = SleepStudyPreference.objects.get(user=request.user)
            recommendation = check_and_redistribute(request.user, preference)
        except SleepStudyPreference.DoesNotExist:
            pass

        response_data = {
            'message': 'Assignment added successfully!',
            'id': task.task_id,
            'cls_score': cls_score,
            'risk_level': risk_level,
        }

        if recommendation:
            response_data['recommendation'] = {
                'alert': recommendation['alert'],
                'suggestion': recommendation['suggestion'],
                'reduction': recommendation['reduction'],
                'session_id': recommendation['session'].session_id,
                'suggested_date': str(recommendation['suggested_date']),
            }

        return Response(response_data, status=status.HTTP_201_CREATED)


@api_view(['PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def assignment_detail(request, task_id):

    # Get the task
    try:
        task = Task.objects.get(task_id=task_id, user=request.user)
    except Task.DoesNotExist:
        return Response(
            {'error': 'Assignment not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    # DELETE — Remove assignment
    if request.method == 'DELETE':
        task.delete()
        return Response(
            {'message': 'Assignment deleted successfully!'},
            status=status.HTTP_200_OK
        )

    # PUT — Update assignment
    if request.method == 'PUT':
        course_code = request.data.get('course_code', task.course_code)
        title = request.data.get('title', task.title)
        deadline = request.data.get('deadline', str(task.deadline))
        hours = request.data.get('hours', task.hours)
        difficulty = request.data.get('difficulty', task.difficulty)

        # Convert deadline
        try:
            deadline_date = date.fromisoformat(str(deadline))
        except ValueError:
            return Response(
                {'error': 'Invalid deadline format'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Convert difficulty string to integer
        difficulty_map = {'easy': 1, 'medium': 2, 'hard': 3}
        if isinstance(difficulty, str):
            difficulty_int = difficulty_map.get(difficulty.lower(), 1)
            difficulty_str = difficulty.lower()
        else:
            difficulty_int = difficulty
            diff_str = {1: 'easy', 2: 'medium', 3: 'hard'}
            difficulty_str = diff_str.get(difficulty_int, 'easy')

        # Recalculate CLS using string difficulty
        cls_score = calculate_cls(difficulty_str, float(hours), deadline_date)
        risk_level = get_risk_level(cls_score)

        # Update task
        task.course_code = course_code.upper()
        task.title = title
        task.deadline = deadline_date
        task.hours = float(hours)
        task.difficulty = difficulty_int
        task.cls_score = cls_score
        task.risk_level = risk_level
        task.save()

        # Delete old sessions and regenerate
        StudySession.objects.filter(task=task).delete()

        try:
            preference = SleepStudyPreference.objects.get(user=request.user)
            sessions = generate_study_sessions(task, preference)
            
            hours_saved = 0
            for session in sessions:
                StudySession.objects.create(
                    task=task,
                    user=request.user,
                    scheduled_date=session['scheduled_date'],
                    scheduled_hours=session['scheduled_hours'],
                    cls_contribution=session['cls_contribution'],
                )
                hours_saved += session['scheduled_hours']

        except SleepStudyPreference.DoesNotExist:
            pass

        # Check for overload after updating sessions
        recommendation = None
        try:
            preference = SleepStudyPreference.objects.get(user=request.user)
            recommendation = check_and_redistribute(request.user, preference)
        except SleepStudyPreference.DoesNotExist:
            pass

        response_data = {
            'message': 'Assignment updated successfully!',
            'cls_score': cls_score,
            'risk_level': risk_level,
            'debug': {
                'task_hours': task.hours,
                'sessions_generated': len(sessions) if 'sessions' in dir() else 0,
                'hours_scheduled': round(hours_saved, 2) if 'hours_saved' in dir() else 0,
            }
        }

        if recommendation:
            response_data['recommendation'] = {
                'alert': recommendation['alert'],
                'suggestion': recommendation['suggestion'],
                'reduction': recommendation['reduction'],
                'session_id': recommendation['session'].session_id,
                'suggested_date': str(recommendation['suggested_date']),
            }

        return Response(response_data, status=status.HTTP_200_OK)