from django import forms
from django.utils.text import slugify

from .models import Repository


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


class RepositoryForm(AccessibleFormMixin, forms.ModelForm):
    class Meta:
        model = Repository
        fields = ['name', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'maxlength': 100}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'maxlength': 1000}),
        }

    def __init__(self, *args, team=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.team = team
        self.fields['name'].label = 'Repository name'
        self.fields['description'].label = 'Description'

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        slug = slugify(name)
        if not slug or len(slug) > 100:
            raise forms.ValidationError('Use a repository name with letters or numbers.')
        if self.team and Repository.objects.filter(team=self.team, slug=slug).exists():
            raise forms.ValidationError('A repository with this name already exists for your team.')
        return name

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.slug = slugify(self.cleaned_data['name'])
        if commit:
            instance.save()
        return instance


class BranchForm(AccessibleFormMixin, forms.Form):
    name = forms.CharField(max_length=100, widget=forms.TextInput(attrs={'class': 'form-control'}), label='Branch name')
    source_branch = forms.CharField(max_length=100, widget=forms.TextInput(attrs={'class': 'form-control'}), label='Source branch')


class MergeRequestForm(AccessibleFormMixin, forms.Form):
    title = forms.CharField(max_length=160, widget=forms.TextInput(attrs={
        'class': 'form-control form-control-sm', 'id': 'mr-title',
        'placeholder': 'Describe your change briefly',
    }))
    source_branch = forms.ChoiceField(widget=forms.Select(attrs={
        'class': 'form-select form-select-sm', 'id': 'mr-source',
    }))
    target_branch = forms.ChoiceField(widget=forms.Select(attrs={
        'class': 'form-select form-select-sm', 'id': 'mr-target',
    }))
    reviewers = forms.MultipleChoiceField(required=False, widget=forms.SelectMultiple(attrs={
        'class': 'form-select form-select-sm', 'id': 'mr-reviewers',
    }))
    description = forms.CharField(required=False, max_length=5000, widget=forms.Textarea(attrs={
        'class': 'form-control form-control-sm', 'id': 'mr-description', 'rows': 4,
        'placeholder': 'Explain what this changes and why',
    }))

    def __init__(self, *args, branches=(), members=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['source_branch'].choices = [(branch, branch) for branch in branches]
        self.fields['target_branch'].choices = [(branch, branch) for branch in branches]
        self.fields['reviewers'].choices = [
            (str(member.user_id), member.user.get_full_name() or member.user.username)
            for member in members
        ]

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('source_branch') and cleaned.get('source_branch') == cleaned.get('target_branch'):
            self.add_error('target_branch', 'Choose a different target branch.')
        return cleaned


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    widget = MultipleFileInput

    def clean(self, data, initial=None):
        if not data:
            return []
        values = data if isinstance(data, (list, tuple)) else [data]
        # Two file inputs share this field name (folder picker + optional
        # archive picker). Browsers may submit the unused picker as an empty
        # UploadedFile; Django treats its blank filename as a validation error.
        values = [value for value in values if getattr(value, 'name', None)]
        return [super(MultipleFileField, self).clean(value, initial) for value in values]


class UploadForm(AccessibleFormMixin, forms.Form):
    upload = MultipleFileField(required=False, widget=MultipleFileInput(attrs={'class': 'form-control', 'multiple': True}), label='Folder files or ZIP archive')
    upload_mode = forms.ChoiceField(choices=[('keep', 'Keep missing files'), ('replace', 'Replace everything')], widget=forms.Select(attrs={'class': 'form-select'}), label='Upload mode')

    def clean_upload(self):
        uploads = self.cleaned_data['upload']
        if not uploads:
            raise forms.ValidationError('Select a folder, ZIP archive, or one or more files.')
        return uploads


class CommitForm(AccessibleFormMixin, forms.Form):
    commit_message = forms.CharField(max_length=200, widget=forms.TextInput(attrs={'class': 'form-control', 'maxlength': 200}), label='Commit message')
    secret_ack = forms.BooleanField(required=False, label='I reviewed the safety warnings and still want to continue.')

    def __init__(self, *args, secret_findings=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.secret_findings = secret_findings or []
        self.fields['secret_ack'].widget.attrs['class'] = 'form-check-input'

    def clean(self):
        cleaned = super().clean()
        if self.secret_findings and not cleaned.get('secret_ack'):
            self.add_error('secret_ack', 'Review the detected credential warnings before committing.')
        return cleaned
