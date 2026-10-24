from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from student.models import (Announcement, Hackathon, MentorRequest, Milestone, Notification,
                            Sprint, Task, Team, TeamMembership)


class Command(BaseCommand):
    help = 'Creates demo data for the HackFlow student workspace.'

    def handle(self, *args, **options):
        User = get_user_model()
        student, _ = User.objects.get_or_create(username='camille.laurent', defaults={
            'email': 'camille.laurent@etu.univ.fr', 'first_name': 'Camille', 'last_name': 'Laurent',
            'role': 'student', 'school': 'HackFlow University', 'study_level': 'Master 2',
            'specialty': 'Lead Dev Fullstack', 'skills': ['Django', 'React', 'Docker'],
            'bio': 'Captain of the EcoTrack team.'})
        student.email = 'camille.laurent@etu.univ.fr'
        student.first_name, student.last_name, student.role = 'Camille', 'Laurent', 'student'
        student.school = 'HackFlow University'
        student.study_level = 'Master 2'
        student.specialty = 'Full-Stack Lead Developer'
        student.skills = ['Django', 'React', 'Docker']
        student.bio = 'Captain of the EcoTrack team.'
        student.set_password('HackFlow2026!')
        student.save()
        members = [
            ('youssef.elmansouri', 'Youssef', 'El Mansouri', 'youssef.m@etu.univ.fr', 'Front-End & Mobile Developer', ['React Native', 'Tailwind', 'TypeScript']),
            ('eleonore.morin', 'Éléonore', 'Morin', 'eleonore.m@etu.univ.fr', 'Product Designer UI/UX', ['Figma', 'User Research', 'Design System']),
            ('lucas.bernard', 'Lucas', 'Bernard', 'lucas.b@etu.univ.fr', 'Back-End & API Developer', ['Python', 'PostgreSQL', 'FastAPI']),
        ]
        people = [student]
        for username, first, last, email, specialty, skills in members:
            user, _ = User.objects.get_or_create(username=username, defaults={'first_name': first, 'last_name': last,
                'email': email, 'role': 'student', 'specialty': specialty, 'skills': skills})
            user.specialty, user.skills = specialty, skills
            user.save(update_fields=['specialty', 'skills'])
            people.append(user)

        mentor, _ = User.objects.get_or_create(username='marc.dubois', defaults={
            'first_name': 'Marc', 'last_name': 'Dubois', 'email': 'marc.dubois@hackflow.fr',
            'role': 'mentor', 'specialty': 'Django & Cloud'})

        now = timezone.now()
        hackathon, _ = Hackathon.objects.update_or_create(name='HackFlow', edition='2026 Edition', defaults={
            'starts_at': now - timedelta(hours=13, minutes=18), 'ends_at': now + timedelta(hours=34, minutes=42), 'is_active': True})
        team, _ = Team.objects.update_or_create(hackathon=hackathon, name='EcoTrack', defaults={
            'category': 'Climate & Energy', 'description': "Make the green transition accessible and engaging on university campuses with AI.",
            'table_number': 'Table 14', 'room': 'Halle Informatique', 'max_members': 5, 'captain': student,
            'seeking_skill': 'Data Scientist / AI Engineer (Prompt Engineering & Climate Models)',
            'project_name': 'EcoTrack - Smart Green Campus',
            'project_pitch': "A web and mobile app that measures the energy and carbon savings of student initiatives.",
            'cover_image_url': 'https://images.unsplash.com/photo-1497435334941-8c899ee9e8e9?w=1200&auto=format&fit=crop&q=80'})
        for index, user in enumerate(people):
            TeamMembership.objects.update_or_create(team=team, user=user, defaults={'role': 'Captain & Full-Stack Lead Developer' if index == 0 else members[index-1][4]})

        milestone_data = [
            ('Kick-off & Ideation', -11, 'done'), ('Concept review with a mentor', -5, 'done'),
            ('Milestone 1: Architecture & Wireframes', 4.25, 'active'),
            ('Milestone 2: Functional MVP submission', 20, 'upcoming'), ('Final Pitch to the Jury', 28, 'upcoming')]
        for order, (title, hours, status) in enumerate(milestone_data):
            Milestone.objects.update_or_create(hackathon=hackathon, title=title, defaults={
                'due_at': now + timedelta(hours=hours), 'order': order, 'status': status})
        for title, author, category, age_minutes in [
            ('The pizza buffet is open in Building B!', 'Alexandre (Organizer)', 'Logistics', 25),
            ('Reminder: Cloud mentors are available in the #devops Discord channel', 'HackFlow Staff', 'Mentoring', 60)]:
            Announcement.objects.update_or_create(hackathon=hackathon, title=title, defaults={
                'author': author, 'category': category, 'published_at': now - timedelta(minutes=age_minutes)})

        sprint, _ = Sprint.objects.update_or_create(team=team, name='Sprint 1', defaults={
            'goal': team.project_pitch, 'starts_at': now - timedelta(hours=13),
            'ends_at': hackathon.ends_at, 'status': Sprint.Status.ACTIVE})

        task_titles = [
            ('Design the 5 key screens in Figma', 'Design & UX', 'done'),
            ('Set up the GitHub repository and README', 'DevOps / Infra', 'done'),
            ('Design the relational SQLite database schema', 'Backend', 'done'),
            ('Build the OAuth sign-in flow', 'Backend', 'done'),
            ('Define campus carbon indicators', 'Backend', 'done'),
            ('Prepare test data', 'Backend', 'done'),
            ('Build the component UI kit', 'Design & UX', 'done'),
            ('Set up the CI pipeline', 'DevOps / Infra', 'done'),
            ('Write the project presentation', 'Pitch & Slides', 'done'),
            ('Validate the user journeys', 'Design & UX', 'done'),
            ('Build the first API endpoints', 'Backend', 'done'),
            ('Set up the development environment', 'DevOps / Infra', 'done'),
            ('Write the 3-minute video pitch script', 'Pitch & Slides', 'todo'),
            ('Generate SSL certificates on the staging server', 'DevOps / Infra', 'todo'),
            ('Test WCAG accessibility contrasts', 'Design & UX', 'todo'),
            ('Integrate the carbon estimation API', 'Backend', 'in_progress'),
            ('Finalize the user dashboard components', 'Frontend', 'in_progress'),
            ("Revue de code de la route d’authentification OAuth", 'Backend', 'review'),
        ]
        for index, (title, category, status) in enumerate(task_titles):
            Task.objects.update_or_create(team=team, title=title, defaults={
                'sprint': sprint,
                'category': category, 'status': status, 'priority': 'high' if index in (12, 15) else 'normal',
                'assignee': people[index % len(people)], 'deadline': now + timedelta(hours=12 + index)})

        # Do not seed fictional URLs as if they were working team resources.

        for number in range(1, 4):
            MentorRequest.objects.update_or_create(student=student, subject=f'Resolved mentor request {number}', defaults={
                'team': team, 'category': 'Technical / Back-end', 'description': 'Resolved demo request.',
                'urgency': 'normal', 'status': 'resolved', 'resolution_note': 'Mentor advice recorded.'})
        MentorRequest.objects.update_or_create(student=student, subject='CORS and SameSite cookie issue with the Django API', defaults={
            'team': team, 'mentor': mentor, 'category': 'Technical / Back-end', 'description': 'Browser demo blocker.',
            'urgency': 'blocking', 'status': 'accepted', 'meeting_url': 'https://meet.google.com/abc-hackflow-demo'})
        Notification.objects.filter(user=student).delete()
        Notification.objects.create(user=student, title='Mentor assigned!', message='Sarah (Data/AI) accepted your help request.', icon='bi-check-circle-fill')
        Notification.objects.create(user=student, title='Milestone reminder', message='Submit the architecture prototype before 6:00 PM.', icon='bi-clock-history')
        self.stdout.write(self.style.SUCCESS('Student demo data created. Username: camille.laurent / Password: HackFlow2026!'))
