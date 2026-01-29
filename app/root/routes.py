from flask import redirect, url_for, session, request, flash
from flask_login import current_user, login_required
from flask_babel import lazy_gettext as _
from app.root import bp

@bp.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.is_admin:
            return redirect(url_for('admin.index'))
        else:
            return redirect(url_for('dashboard.dashboard_home'))
    return redirect(url_for('auth.login'))

@bp.route('/personal_dashboard') # New route
@login_required # Ensure only logged-in users can access this
def personal_dashboard_redirect():
    return redirect(url_for('dashboard.dashboard_home'))

@bp.route('/switch_facility/<int:facility_id>')
@login_required
def switch_facility(facility_id):
    # Verify user has access to this facility (and is approved)
    from app.models import UserFacilityRole
    ufr = UserFacilityRole.query.filter_by(
        user_id=current_user.id,
        facility_id=facility_id,
        is_approved=True
    ).first()
    
    if ufr:
        session['current_facility_id'] = facility_id
        flash(_("Switched to facility: %(name)s", name=ufr.facility.name), 'success')
    else:
        flash(_("You do not have access to this facility."), 'danger')
        
    next_url = request.args.get('next')
    return redirect(next_url or request.referrer or url_for('dashboard.dashboard_home'))

@bp.route('/language/<language>')
def language_switch(language):
    session['language'] = language
    return redirect(request.referrer)
