from django import forms
from decimal import Decimal, InvalidOperation
from django.forms.models import inlineformset_factory
from .models import CareerRequirement, Opportunity, CareerApplication, OpportunitySkill


class OpportunityForm(forms.ModelForm):
    languages = forms.CharField(required=False, help_text='Comma-separated, for example: French, English')
    required_skills = forms.CharField(required=False, help_text='Enter Skill=weight pairs, e.g. Python=25, Django=15; weights are normalized across all requirements.')
    preferred_skills = forms.CharField(required=False, help_text='Enter Skill=weight pairs, e.g. Docker=10; weights are normalized across all requirements.')
    education_weight = forms.DecimalField(required=False, min_value=0, max_value=100, initial=20, decimal_places=2)
    experience_weight = forms.DecimalField(required=False, min_value=0, max_value=100, initial=15, decimal_places=2)
    language_weight = forms.DecimalField(required=False, min_value=0, max_value=100, initial=10, decimal_places=2)
    location_weight = forms.DecimalField(required=False, min_value=0, max_value=100, initial=10, decimal_places=2)
    education_mandatory = forms.BooleanField(required=False, label='Mandatory eligibility')
    experience_mandatory = forms.BooleanField(required=False, label='Mandatory eligibility')
    language_mandatory = forms.BooleanField(required=False, label='Mandatory eligibility')
    location_mandatory = forms.BooleanField(required=False, label='Mandatory eligibility')

    class Meta:
        model = Opportunity
        fields = ['title', 'company', 'description', 'opportunity_type', 'education', 'experience', 'location', 'work_mode', 'languages', 'publication_date', 'deadline', 'salary', 'application_url', 'internal_application', 'status', 'moderation_note']
        widgets = {'description': forms.Textarea(attrs={'rows': 8}), 'languages': forms.TextInput(attrs={'placeholder': 'French, English'}), 'publication_date': forms.DateInput(attrs={'type': 'date'}), 'deadline': forms.DateInput(attrs={'type': 'date'})}

    def clean_languages(self):
        return [item.strip() for item in self.cleaned_data['languages'].split(',') if item.strip()]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_existing = bool(self.instance and self.instance.pk)
        for name, field in self.fields.items():
            checkbox = isinstance(field.widget, forms.CheckboxInput)
            select = isinstance(field.widget, (forms.Select, forms.SelectMultiple))
            field.widget.attrs.setdefault('class', 'form-check-input' if checkbox else 'form-select' if select else 'form-control')
        self.fields['description'].widget.attrs.setdefault('rows', 8)
        self.fields['moderation_note'].widget.attrs.setdefault('rows', 3)
        self.fields['title'].widget.attrs.setdefault('placeholder', 'e.g. Backend Developer Intern')
        self.fields['company'].widget.attrs.setdefault('placeholder', 'Company or organization')
        self.fields['location'].widget.attrs.setdefault('placeholder', 'City, country or remote')
        if self.is_existing:
            self.initial['languages'] = ', '.join(self.instance.languages or [])
            for kind, field_name in (('required', 'required_skills'), ('preferred', 'preferred_skills')):
                self.initial[field_name] = ', '.join(f'{skill.name}={skill.weight}' for skill in self.instance.skills.filter(kind=kind))
            for kind, field_name in ((CareerRequirement.Kind.EDUCATION, 'education_weight'),
                                     (CareerRequirement.Kind.EXPERIENCE, 'experience_weight'),
                                     (CareerRequirement.Kind.LANGUAGE, 'language_weight'),
                                     (CareerRequirement.Kind.LOCATION, 'location_weight')):
                rows = self.instance.requirements.filter(kind=kind)
                if rows.exists():
                    self.initial[field_name] = sum((row.weight for row in rows), Decimal(0))
                    self.initial[field_name.replace('_weight', '_mandatory')] = rows.filter(mandatory=True).exists()

    def _parse_skills(self, field_name):
        result = []
        for part in self.cleaned_data.get(field_name, '').split(','):
            part = part.strip()
            if not part:
                continue
            name, sep, value = part.rpartition('=')
            if not sep:
                name, value = part, '1'
            try:
                weight = Decimal(value.strip())
            except InvalidOperation:
                self.add_error(field_name, 'Use Skill=weight format, for example Python=25.')
                continue
            if not name.strip() or weight < 0 or weight > 100:
                self.add_error(field_name, 'Skill names must be present and weights must be between 0 and 100.')
                continue
            result.append((name.strip()[:100], weight))
        if len({name.casefold() for name, _ in result}) != len(result):
            self.add_error(field_name, 'Each skill may appear only once in a list.')
        return result

    def clean(self):
        cleaned = super().clean()
        self.required_skill_rows = self._parse_skills('required_skills')
        self.preferred_skill_rows = self._parse_skills('preferred_skills')
        return cleaned

    def raw_requirements(self, requirement_formset):
        rows = []
        for field_name, kind, mandatory in (('required_skill_rows', OpportunitySkill.Kind.REQUIRED, True), ('preferred_skill_rows', OpportunitySkill.Kind.PREFERRED, False)):
            rows.extend({'model': 'skill', 'name': name, 'kind': kind, 'mandatory': mandatory, 'weight': weight}
                        for name, weight in getattr(self, field_name, []))
        fields = (
            ('education', 'education_weight', 'education_mandatory', CareerRequirement.Kind.EDUCATION),
            ('experience', 'experience_weight', 'experience_mandatory', CareerRequirement.Kind.EXPERIENCE),
            ('languages', 'language_weight', 'language_mandatory', CareerRequirement.Kind.LANGUAGE),
            ('location', 'location_weight', 'location_mandatory', CareerRequirement.Kind.LOCATION),
        )
        for value_field, weight_field, mandatory_field, kind in fields:
            value = self.cleaned_data.get(value_field)
            values = value if isinstance(value, list) else [value]
            if value_field == 'location' and self.cleaned_data.get('work_mode') not in ('', Opportunity.WorkMode.UNSPECIFIED):
                values.append(self.cleaned_data.get('work_mode'))
            values = [item.strip() for item in values if item and item.strip()]
            if values:
                each_weight = Decimal(str(self.cleaned_data.get(weight_field) or 0)) / len(values)
                rows.extend({'model': 'requirement', 'name': item[:160], 'kind': kind, 'description': item[:500],
                    'mandatory': self.cleaned_data.get(mandatory_field, False), 'weight': each_weight}
                    for item in values)
        for form in requirement_formset.forms:
            if not hasattr(form, 'cleaned_data') or not form.cleaned_data or form.cleaned_data.get('DELETE'):
                continue
            data = form.cleaned_data
            if data.get('name'):
                rows.append({'model': 'requirement', 'name': data['name'].strip(), 'kind': data['kind'],
                    'description': data.get('description', '').strip(), 'mandatory': data.get('mandatory', False),
                    'weight': data.get('weight') or Decimal(0), 'instance': form.instance})
        return rows

    def validate_weights(self, requirement_formset):
        rows = self.raw_requirements(requirement_formset)
        for row in rows:
            if row['weight'] < 0 or row['weight'] > 100:
                self.add_error(None, 'Every scored requirement weight must be between 0 and 100.')
                return False
        if rows and sum((row['weight'] for row in rows), Decimal(0)) <= 0:
            self.add_error(None, 'Set a positive weight on at least one scored requirement.')
            return False
        return True

    def save_requirements(self, opportunity, requirement_formset):
        rows = self.raw_requirements(requirement_formset)
        total = sum((row['weight'] for row in rows), Decimal(0))
        normalized, running = [], Decimal(0)
        for row in rows:
            weight = (row['weight'] * Decimal(100) / total).quantize(Decimal('0.01')) if total else Decimal(0)
            normalized.append((row, weight))
            running += weight
        if normalized:
            row, weight = normalized[-1]
            normalized[-1] = (row, weight + Decimal(100) - running)
        opportunity.skills.all().delete()
        opportunity.requirements.filter(kind__in=[CareerRequirement.Kind.EDUCATION, CareerRequirement.Kind.EXPERIENCE,
            CareerRequirement.Kind.LANGUAGE, CareerRequirement.Kind.LOCATION]).delete()
        for row, weight in normalized:
            if row['model'] == 'skill':
                OpportunitySkill.objects.create(opportunity=opportunity, name=row['name'], kind=row['kind'],
                    verified=row['mandatory'], weight=weight)
            else:
                instance = row.get('instance')
                if instance and instance.pk:
                    instance.name, instance.kind, instance.description = row['name'], row['kind'], row['description']
                    instance.mandatory, instance.weight = row['mandatory'], weight
                    instance.save()
                else:
                    CareerRequirement.objects.create(opportunity=opportunity, name=row['name'], kind=row['kind'],
                        description=row['description'], mandatory=row['mandatory'], weight=weight)
        for form in requirement_formset.deleted_forms:
            if form.instance.pk:
                form.instance.delete()


class CareerRequirementForm(forms.ModelForm):
    class Meta:
        model = CareerRequirement
        fields = ('kind', 'name', 'description', 'weight', 'mandatory')
        widgets = {'description': forms.TextInput(attrs={'placeholder': 'How this requirement will be assessed'}),
                   'weight': forms.NumberInput(attrs={'min': 0, 'max': 100, 'step': '0.01'}),
                   'mandatory': forms.CheckboxInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['kind'].choices = [(CareerRequirement.Kind.PROJECT, 'Project experience'), (CareerRequirement.Kind.OTHER, 'Other eligibility')]
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-check-input' if isinstance(field.widget, forms.CheckboxInput) else 'form-select' if isinstance(field.widget, forms.Select) else 'form-control')


CareerRequirementFormSet = inlineformset_factory(Opportunity, CareerRequirement, form=CareerRequirementForm,
    extra=3, can_delete=True, max_num=30, validate_max=True)

class ApplicationForm(forms.ModelForm):
    class Meta:
        model = CareerApplication
        fields = ['portfolio_url', 'note']
        widgets = {'note': forms.TextInput(attrs={'maxlength': 500})}


class OrganizerApplicationUpdateForm(forms.Form):
    status = forms.ChoiceField(choices=[
        (CareerApplication.Status.REVIEW, 'Under review'),
        (CareerApplication.Status.INTERVIEW, 'Interview'),
        (CareerApplication.Status.ACCEPTED, 'Accepted'),
        (CareerApplication.Status.REJECTED, 'Rejected'),
        (CareerApplication.Status.WITHDRAWN, 'Withdrawn'),
    ], widget=forms.Select(attrs={'class': 'form-select form-select-sm mb-2'}))
    interview_at = forms.DateTimeField(
        required=False,
        input_formats=['%Y-%m-%dT%H:%M'],
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control form-control-sm'}, format='%Y-%m-%dT%H:%M'),
    )
    organizer_update = forms.CharField(
        required=False, max_length=500,
        widget=forms.Textarea(attrs={'rows': 2, 'class': 'form-control form-control-sm', 'placeholder': 'Message or interview details for the student'}),
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('status') == CareerApplication.Status.INTERVIEW and not cleaned.get('interview_at'):
            self.add_error('interview_at', 'Set an interview date and time before notifying the student.')
        return cleaned
