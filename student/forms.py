from django import forms
from django.contrib.auth import get_user_model
from django.core.validators import FileExtensionValidator
from django.utils.translation import gettext_lazy as _

from .models import AITaskJob, DirectMessage, MentorRequest, Resource, Sprint, Submission, Task, Team, TeamInvitation

User = get_user_model()


class AccessibleFormMixin:
    """Expose required state consistently to assistive technology."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['aria-required'] = 'true' if field.required else 'false'

    def full_clean(self):
        super().full_clean()
        for name, field in self.fields.items():
            if self.errors.get(name):
                field.widget.attrs['aria-invalid'] = 'true'
                field.widget.attrs['aria-describedby'] = f'{field.widget.attrs.get("id", f"id_{name}")}_errors'


class StyledModelForm(AccessibleFormMixin, forms.ModelForm):
    """Apply the field classes used by the templates."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = 'form-select' if isinstance(field.widget, (forms.Select, forms.SelectMultiple)) else 'form-control'
            classes = field.widget.attrs.get('class', '').split()
            if css not in classes:
                classes.append(css)
            field.widget.attrs['class'] = ' '.join(classes)

    def full_clean(self):
        super().full_clean()
        for name, field in self.fields.items():
            if self.errors.get(name):
                classes = field.widget.attrs.get('class', '').split()
                if 'is-invalid' not in classes:
                    classes.append('is-invalid')
                field.widget.attrs['class'] = ' '.join(classes)


class TeamForm(StyledModelForm):
    class Meta:
        model = Team
        fields = ['name', 'category', 'description', 'table_number', 'room', 'seeking_skill']
        labels = {'name': _('Team name'), 'category': _('Category'), 'description': _('Project description'),
                  'table_number': _('Table number'), 'room': _('Room'), 'seeking_skill': _('Skill needed')}
        widgets = {'description': forms.Textarea(attrs={'rows': 3})}


class InvitationForm(StyledModelForm):
    class Meta:
        model = TeamInvitation
        fields = ['email']
        labels = {'email': _('Invitee email')}

    def __init__(self, *args, team=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.team = team

    def clean_email(self):
        email = self.cleaned_data['email'].lower()
        user = User.objects.filter(email__iexact=email, role='student').first()
        if user and user.team_memberships.exists():
            raise forms.ValidationError(_('This student is already on a team.'))
        self.invited_user = user
        return email


class ResourceForm(StyledModelForm):
    class Meta:
        model = Resource
        fields = ['title', 'url', 'document', 'kind']
        labels = {'title': _('Resource title'), 'url': _('Link'), 'document': _('Document'), 'kind': _('Resource type')}

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get('url') and not cleaned_data.get('document'):
            self.add_error('url', _('Add a valid link or upload a document.'))
        return cleaned_data


class TaskForm(StyledModelForm):
    class Meta:
        model = Task
        fields = ['title', 'description', 'category', 'assignee', 'priority', 'deadline']
        labels = {'title': _('Task title'), 'description': _('Description'), 'category': _('Category'),
                  'assignee': _('Assignee'), 'priority': _('Priority'), 'deadline': _('Deadline')}
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
            'deadline': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }

    def __init__(self, *args, team=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['assignee'].queryset = User.objects.filter(team_memberships__team=team).distinct() if team else User.objects.none()


class AITaskJobForm(AccessibleFormMixin, forms.Form):
    prompt = forms.CharField(max_length=1000, widget=forms.Textarea(attrs={
        'rows': 4, 'maxlength': 1000, 'class': 'form-control w-100',
        'placeholder': _('Describe a feature or goal for your team...'),
    }))
    sprint = forms.ModelChoiceField(queryset=Sprint.objects.none(), required=False, empty_label=_('No sprint selected'),
                                      widget=forms.Select(attrs={'class': 'form-select w-100'}))

    def __init__(self, *args, team=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['sprint'].queryset = Sprint.objects.filter(team=team) if team else Sprint.objects.none()


class MentorRequestForm(StyledModelForm):
    category = forms.ChoiceField(choices=[
        ('Back-End Development & Databases', _('Back-End Development & Databases')),
        ('Front-End Development & Frameworks', _('Front-End Development & Frameworks')),
        ('AI, LLMs & Machine Learning', _('AI, LLMs & Machine Learning')),
        ('DevOps, Docker & Cloud Deployment', _('DevOps, Docker & Cloud Deployment')),
        ('UI/UX Design & User Experience', _('UI/UX Design & User Experience')),
        ('Pitch & Presentation Structure', _('Pitch & Presentation Structure')),
    ])

    class Meta:
        model = MentorRequest
        fields = ['subject', 'category', 'urgency', 'meeting_url', 'description']
        labels = {'subject': _('Issue / request'), 'category': _('Area of expertise'), 'urgency': _('Urgency'),
                  'meeting_url': _('Meeting room link'), 'description': _('Detailed description')}


class SubmissionForm(StyledModelForm):
    repository_branch = forms.CharField(required=False, max_length=100, label=_('Repository branch'),
        widget=forms.TextInput(attrs={'placeholder': 'main'}))
    file = forms.FileField(
        required=False,
        validators=[FileExtensionValidator(['zip'])],
        label=_('Project ZIP archive'),
    )

    class Meta:
        model = Submission
        fields = ['project_name', 'category', 'description', 'project_summary', 'github_url', 'demo_url', 'video_url', 'file', 'repository']
        labels = {'project_name': _('Project name'), 'category': _('Challenge'), 'description': _('Project pitch'),
                  'github_url': _('GitHub / GitLab repository URL'), 'demo_url': _('Online demo URL'),
                  'video_url': _('Demo video URL'), 'file': _('Pitch deck PDF'), 'repository': _('HackFlow repository'),
                  'project_summary': _('Project summary')}

    def __init__(self, *args, team=None, **kwargs):
        super().__init__(*args, **kwargs)
        from repositories.models import Repository
        self.fields['repository'].required = False
        self.fields['repository'].queryset = Repository.objects.filter(team=team) if team else Repository.objects.none()
        self.fields['project_summary'].widget.attrs.setdefault('rows', 5)
        if self.instance and self.instance.pk and self.instance.repository_id:
            self.fields['repository_branch'].initial = self.instance.repository.default_branch

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('repository') and not cleaned.get('repository_branch'):
            self.add_error('repository_branch', _('Choose a branch to freeze for this submission.'))
        if not cleaned.get('repository'):
            cleaned['repository_branch'] = ''
        return cleaned


class MatchingFilterForm(AccessibleFormMixin, forms.Form):
    skill = forms.CharField(required=False)
    role = forms.CharField(required=False)


class DirectMessageForm(AccessibleFormMixin, forms.ModelForm):
    class Meta:
        model = DirectMessage
        fields = ['body']
        widgets = {'body': forms.Textarea(attrs={
            'class': 'form-control', 'rows': 3,
            'placeholder': 'Write your message…',
        })}
