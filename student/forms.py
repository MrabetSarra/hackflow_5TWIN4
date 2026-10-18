from django import forms
from django.contrib.auth import get_user_model
from django.core.validators import FileExtensionValidator

from .models import DirectMessage, MentorRequest, Resource, Submission, Task, Team, TeamInvitation

User = get_user_model()


class StyledModelForm(forms.ModelForm):
    """Apply the field classes used by the templates."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = 'form-select' if isinstance(field.widget, (forms.Select, forms.SelectMultiple)) else 'form-control'
            field.widget.attrs.setdefault('class', css)


class TeamForm(StyledModelForm):
    class Meta:
        model = Team
        fields = ['name', 'category', 'description', 'table_number', 'room', 'seeking_skill']
        labels = {'name': 'Team name', 'category': 'Category', 'description': 'Project description',
                  'table_number': 'Table number', 'room': 'Room', 'seeking_skill': 'Skill needed'}
        widgets = {'description': forms.Textarea(attrs={'rows': 3})}


class InvitationForm(StyledModelForm):
    class Meta:
        model = TeamInvitation
        fields = ['email']
        labels = {'email': 'Invitee email'}

    def __init__(self, *args, team=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.team = team

    def clean_email(self):
        email = self.cleaned_data['email'].lower()
        user = User.objects.filter(email__iexact=email, role='student').first()
        if user and user.team_memberships.exists():
            raise forms.ValidationError('This student is already on a team.')
        self.invited_user = user
        return email


class ResourceForm(StyledModelForm):
    class Meta:
        model = Resource
        fields = ['title', 'url', 'document', 'kind']
        labels = {'title': 'Resource title', 'url': 'Link', 'document': 'Document', 'kind': 'Resource type'}

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get('url') and not cleaned_data.get('document'):
            raise forms.ValidationError('Add a valid link or upload a document.')
        return cleaned_data


class TaskForm(StyledModelForm):
    class Meta:
        model = Task
        fields = ['title', 'description', 'category', 'assignee', 'priority', 'deadline']
        labels = {'title': 'Task title', 'description': 'Description', 'category': 'Category',
                  'assignee': 'Assignee', 'priority': 'Priority', 'deadline': 'Deadline'}
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
            'deadline': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }

    def __init__(self, *args, team=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['assignee'].queryset = User.objects.filter(team_memberships__team=team).distinct() if team else User.objects.none()


class MentorRequestForm(StyledModelForm):
    class Meta:
        model = MentorRequest
        fields = ['subject', 'category', 'urgency', 'meeting_url', 'description']
        labels = {'subject': 'Issue / request', 'category': 'Area of expertise', 'urgency': 'Urgency',
                  'meeting_url': 'Meeting room link', 'description': 'Detailed description'}


class SubmissionForm(StyledModelForm):
    file = forms.FileField(
        required=False,
        validators=[FileExtensionValidator(['zip'])],
        label='Project ZIP archive',
    )

    class Meta:
        model = Submission
        fields = ['project_name', 'category', 'description', 'github_url', 'demo_url', 'video_url', 'file']
        labels = {'project_name': 'Project name', 'category': 'Challenge', 'description': 'Project pitch',
                  'github_url': 'GitHub / GitLab repository URL', 'demo_url': 'Online demo URL',
                  'video_url': 'Demo video URL', 'file': 'Pitch deck PDF'}


class MatchingFilterForm(forms.Form):
    skill = forms.CharField(required=False)
    role = forms.CharField(required=False)


class DirectMessageForm(forms.ModelForm):
    class Meta:
        model = DirectMessage
        fields = ['body']
        widgets = {'body': forms.Textarea(attrs={
            'class': 'form-control', 'rows': 3,
            'placeholder': 'Write your message…',
        })}
