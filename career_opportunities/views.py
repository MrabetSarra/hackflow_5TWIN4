from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.views.decorators.cache import never_cache
from accounts.decorators import role_required
from .forms import ApplicationForm, CareerRequirementFormSet, OpportunityForm
from .models import ApplicationHistory, CareerApplication, CareerRequirement, Opportunity, OpportunitySkill, SavedOpportunity
from .services.matching import calculate_match, calculate_matches
from .services.cv_analysis import analyze_student_cv
from student.models import Notification


@never_cache
@login_required
def opportunity_list(request):
    role = getattr(request.user, 'role', None)
    if role != 'student':
        if role in ('admin', 'organization'):
            return redirect('dashboard_admin:career_dashboard')
        if role == 'mentor':
            return redirect('mentor:dashboard')
        return redirect('core:landing')

    today = timezone.localdate()
    qs = Opportunity.objects.filter(status=Opportunity.Status.PUBLISHED).filter(
        Q(deadline__isnull=True) | Q(deadline__gte=today)
    ).filter(Q(publication_date__isnull=True) | Q(publication_date__lte=today))
    query = request.GET.get('q', '').strip()
    kind = request.GET.get('type', '')
    location = request.GET.get('location', '').strip()
    work_mode = request.GET.get('work_mode', '')
    skill = request.GET.get('skill', '').strip()
    eligibility_filter = request.GET.get('eligibility', '')
    if query:
        qs = qs.filter(Q(title__icontains=query) | Q(company__icontains=query) | Q(description__icontains=query))
    if kind in Opportunity.Type.values:
        qs = qs.filter(opportunity_type=kind)
    if location:
        qs = qs.filter(location__icontains=location)
    if work_mode in Opportunity.WorkMode.values:
        qs = qs.filter(work_mode=work_mode)
    if skill:
        qs = qs.filter(Q(skills__name__icontains=skill) | Q(requirements__name__icontains=skill)).distinct()
    saved_ids = set(SavedOpportunity.objects.filter(user=request.user).values_list('opportunity_id', flat=True))
    if request.GET.get('saved') == '1':
        qs = qs.filter(pk__in=saved_ids)

    analysis = analyze_student_cv(request.user)
    offers = qs.prefetch_related('skills', 'requirements').distinct()
    offers = list(offers)
    matches = calculate_matches(request.user, offers, cv_analysis=analysis)
    cards = [{'opportunity': offer, 'match': matches[offer.pk], 'saved': offer.pk in saved_ids} for offer in offers]
    if eligibility_filter in ('satisfied', 'unverified', 'failed'):
        cards = [card for card in cards if card['match']['mandatory_status'] == eligibility_filter]
    cards.sort(key=lambda card: (card['match']['score'] is None, -(card['match']['score'] or 0), card['opportunity'].title.casefold()))
    paginator = Paginator(cards, 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    filter_params = request.GET.copy()
    filter_params.pop('page', None)
    skill_options = list(OpportunitySkill.objects.filter(opportunity__status=Opportunity.Status.PUBLISHED)
                         .values_list('name', flat=True).distinct().order_by('name')[:100])
    return render(request, 'career_opportunities/list.html', {
        'cards': page_obj.object_list, 'page_obj': page_obj, 'query': query, 'kind': kind,
        'location': location, 'work_mode': work_mode, 'skill': skill, 'eligibility_filter': eligibility_filter,
        'saved_only': request.GET.get('saved') == '1', 'types': Opportunity.Type.choices,
        'work_modes': Opportunity.WorkMode.choices, 'skill_options': skill_options, 'cv_status': analysis['status'],
        'filter_query': filter_params.urlencode(),
    })


@never_cache
@role_required('student')
def opportunity_detail(request, pk):
    opportunity = get_object_or_404(Opportunity, pk=pk, status=Opportunity.Status.PUBLISHED)
    today = timezone.localdate()
    if opportunity.deadline and opportunity.deadline < today:
        return render(request, 'career_opportunities/unavailable.html', {'opportunity': opportunity}, status=410)
    if opportunity.publication_date and opportunity.publication_date > today:
        raise Http404
    analysis = analyze_student_cv(request.user)
    match = calculate_match(request.user, opportunity, cv_analysis=analysis)
    saved = SavedOpportunity.objects.filter(user=request.user, opportunity=opportunity).exists()
    application = CareerApplication.objects.filter(user=request.user, opportunity=opportunity).first()
    form = ApplicationForm(request.POST or None)
    if request.method == 'POST' and 'apply' in request.POST and form.is_valid():
        already_submitted = application and application.status in {
            CareerApplication.Status.SUBMITTED,
            CareerApplication.Status.REVIEW,
            CareerApplication.Status.INTERVIEW,
            CareerApplication.Status.ACCEPTED,
            CareerApplication.Status.REJECTED,
        }
        if opportunity.internal_application and already_submitted:
            messages.info(request, 'You have already applied for this opportunity. You can follow its status in My applications.')
        elif opportunity.internal_application and not request.user.cv:
            messages.error(request, 'Upload your CV in your HackFlow profile before applying through HackFlow.')
        else:
            application, created = CareerApplication.objects.get_or_create(
                user=request.user, opportunity=opportunity,
                defaults={'status': CareerApplication.Status.SUBMITTED if opportunity.internal_application else CareerApplication.Status.INTENDED},
            )
            if opportunity.internal_application and application.status == CareerApplication.Status.WITHDRAWN:
                application.status = CareerApplication.Status.SUBMITTED
            if opportunity.internal_application and request.user.cv:
                application.cv.name = request.user.cv.name
            for field in ('portfolio_url', 'note'):
                value = form.cleaned_data.get(field)
                if value:
                    setattr(application, field, value)
            application.save()
            ApplicationHistory.objects.get_or_create(application=application, new_status=application.status,
                defaults={'actor': request.user, 'note': 'Application created'})
            messages.success(request, 'Application saved in HackFlow.' if opportunity.internal_application else 'Intention recorded. Confirm your application on the employer website.')
            return redirect('career_opportunities:detail', pk=pk)
    return render(request, 'career_opportunities/detail.html', {
        'opportunity': opportunity, 'match': match, 'saved': saved, 'application': application,
        'form': form, 'cv_status': analysis['status'],
    })

@role_required('student')
@require_POST
def save_toggle(request, pk):
    today = timezone.localdate()
    opportunity = get_object_or_404(Opportunity.objects.filter(status=Opportunity.Status.PUBLISHED)
        .filter(Q(deadline__isnull=True) | Q(deadline__gte=today))
        .filter(Q(publication_date__isnull=True) | Q(publication_date__lte=today)), pk=pk)
    saved, created = SavedOpportunity.objects.get_or_create(user=request.user, opportunity=opportunity)
    if not created:
        saved.delete()
    next_url = request.POST.get('next')
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(next_url)
    return redirect('career_opportunities:list')


@never_cache
@role_required('student')
def my_applications(request):
    qs = CareerApplication.objects.filter(user=request.user).select_related('opportunity').prefetch_related('history')
    query = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    if query:
        qs = qs.filter(Q(opportunity__title__icontains=query) | Q(opportunity__company__icontains=query))
    if status in CareerApplication.Status.values:
        qs = qs.filter(status=status)
    paginator = Paginator(qs, 10)
    page_obj = paginator.get_page(request.GET.get('page'))
    all_apps = CareerApplication.objects.filter(user=request.user)
    counts = {key: all_apps.filter(status=key).count() for key, _ in CareerApplication.Status.choices}
    filters = request.GET.copy()
    filters.pop('page', None)
    return render(request, 'career_opportunities/applications.html', {
        'applications': page_obj.object_list, 'page_obj': page_obj, 'query': query, 'status_filter': status,
        'statuses': CareerApplication.Status.choices, 'counts': counts, 'total_count': sum(counts.values()),
        'filter_query': filters.urlencode(),
    })


@role_required('student')
@require_POST
def application_status(request, pk):
    application = get_object_or_404(CareerApplication, pk=pk, user=request.user)
    new_status = request.POST.get('status')
    allowed = {CareerApplication.Status.INTENDED, CareerApplication.Status.WITHDRAWN, CareerApplication.Status.INTERVIEW, CareerApplication.Status.ACCEPTED, CareerApplication.Status.REJECTED}
    if new_status in allowed:
        old_status = application.status
        application.status = new_status
        application.save(update_fields=['status', 'updated_at'])
        ApplicationHistory.objects.create(application=application, actor=request.user, old_status=old_status, new_status=new_status)
    return redirect('career_opportunities:applications')


def _organizer_view(request):
    return getattr(request.user, 'role', None) in ('admin', 'organization')


@never_cache
@role_required('admin', 'organization')
def organizer_dashboard(request):
    qs = Opportunity.objects.all()
    all_offers = list(qs.only('status', 'deadline'))
    stats = {'total': len(all_offers), 'active': sum(o.status == Opportunity.Status.PUBLISHED and not o.is_expired for o in all_offers), 'pending': sum(o.status == Opportunity.Status.REVIEW for o in all_offers), 'expired': sum(o.is_expired for o in all_offers), 'applications': CareerApplication.objects.count()}
    query = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    filtered = qs.annotate(application_count=Count('applications'))
    if query:
        filtered = filtered.filter(Q(title__icontains=query) | Q(company__icontains=query) | Q(description__icontains=query))
    if status in Opportunity.Status.values:
        filtered = filtered.filter(status=status)
    page_obj = Paginator(filtered.order_by('-publication_date', '-created_at'), 50).get_page(request.GET.get('page'))
    return render(request, 'career_opportunities/organizer.html', {
        'stats': stats, 'opportunities': page_obj.object_list, 'page_obj': page_obj,
        'query': query, 'status_filter': status, 'status_choices': Opportunity.Status.choices,
    })


@never_cache
@role_required('admin', 'organization')
def organizer_create(request):
    form = OpportunityForm(request.POST or None)
    formset = CareerRequirementFormSet(request.POST or None, instance=Opportunity(), queryset=Opportunity.objects.none())
    valid = request.method == 'POST' and form.is_valid() and formset.is_valid()
    if valid and form.validate_weights(formset):
        with transaction.atomic():
            opportunity = form.save(commit=False)
            opportunity.created_by = request.user
            opportunity.save()
            form.save_requirements(opportunity, formset)
        messages.success(request, 'Opportunity saved. Drafts are private; published offers now appear to students.')
        return redirect('dashboard_admin:career_dashboard')
    return render(request, 'career_opportunities/form.html', {
        'form': form, 'requirement_formset': formset, 'title': 'Add opportunity',
    })


@never_cache
@role_required('admin', 'organization')
def organizer_edit(request, pk):
    opportunity = get_object_or_404(Opportunity, pk=pk)
    form = OpportunityForm(request.POST or None, instance=opportunity)
    custom_requirements = opportunity.requirements.filter(kind__in=[CareerRequirement.Kind.PROJECT, CareerRequirement.Kind.OTHER])
    formset = CareerRequirementFormSet(request.POST or None, instance=opportunity, queryset=custom_requirements)
    valid = request.method == 'POST' and form.is_valid() and formset.is_valid()
    if valid and form.validate_weights(formset):
        with transaction.atomic():
            opportunity = form.save()
            form.save_requirements(opportunity, formset)
        messages.success(request, 'Opportunity updated.')
        return redirect('dashboard_admin:career_dashboard')
    return render(request, 'career_opportunities/form.html', {
        'form': form, 'requirement_formset': formset, 'title': 'Review opportunity', 'opportunity': opportunity,
    })


@never_cache
@role_required('admin', 'organization')
def organizer_applications(request):
    applications = CareerApplication.objects.select_related('user', 'opportunity').prefetch_related('history')
    return render(request, 'career_opportunities/organizer_applications.html', {'applications': applications[:200], 'statuses': CareerApplication.Status.choices})


@role_required('admin', 'organization')
@require_POST
def organizer_application_status(request, pk):
    application = get_object_or_404(CareerApplication.objects.select_related('user', 'opportunity'), pk=pk)
    new_status = request.POST.get('status')
    allowed = {CareerApplication.Status.REVIEW, CareerApplication.Status.INTERVIEW, CareerApplication.Status.ACCEPTED, CareerApplication.Status.REJECTED, CareerApplication.Status.WITHDRAWN}
    if new_status in allowed and new_status != application.status:
        old_status = application.status
        application.status = new_status
        application.save(update_fields=['status', 'updated_at'])
        ApplicationHistory.objects.create(application=application, actor=request.user, old_status=old_status, new_status=new_status)
        Notification.objects.create(user=application.user, title='Application status updated', message=f'{application.opportunity.title}: {application.get_status_display()}.', icon='bi-briefcase-fill', url='/careers/applications/')
    return redirect('dashboard_admin:career_applications')


@role_required('admin', 'organization')
def organizer_application_cv(request, pk):
    application = get_object_or_404(CareerApplication, pk=pk)
    if not application.cv:
        raise Http404
    try:
        file_handle = application.cv.open('rb')
    except OSError as exc:
        raise Http404 from exc
    response = FileResponse(file_handle, content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="application-cv.pdf"'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, no-store'
    response['Pragma'] = 'no-cache'
    return response
