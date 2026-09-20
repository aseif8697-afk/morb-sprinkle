from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, Response
from flask_login import login_required, current_user
from app import db
from app.models.sms import SMDRange, SMSNumber, SMSCDR
from app.models.user import User, Role
from app.models.activity import ActivityLog, News
from datetime import datetime, timedelta, date
from functools import wraps
import csv
import io

admin_bp = Blueprint('admin', __name__)

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('auth.login'))
        if not current_user.is_admin():
            flash('Admin access required.', 'danger')
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated

# ============ ADMIN DASHBOARD ============

@admin_bp.route('/')
@admin_required
def index():
    total_users = User.query.count()
    active_users = User.query.filter_by(is_active=True).count()
    total_numbers = SMSNumber.query.count()
    total_ranges = SMDRange.query.count()
    total_cdr = SMSCDR.query.count()
    today = datetime.utcnow().date()
    today_sms = SMSCDR.query.filter(
        db.func.date(SMSCDR.created_at) == today
    ).count()
    recent_news = News.query.filter_by(is_active=True).order_by(
        News.created_at.desc()
    ).limit(5).all()
    return render_template('admin/index.html',
        stats={
            'total_users': total_users,
            'active_users': active_users,
            'total_numbers': total_numbers,
            'total_ranges': total_ranges,
            'total_cdr': total_cdr,
            'today_sms': today_sms
        },
        recent_news=recent_news
    )

# ============ USER MANAGEMENT ============

@admin_bp.route('/users')
@admin_required
def users():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    role_filter = request.args.get('role', '')
    query = User.query
    if search:
        query = query.filter(
            db.or_(
                User.username.like(f'%{search}%'),
                User.email.like(f'%{search}%'),
                User.name.like(f'%{search}%')
            )
        )
    if role_filter:
        role_obj = Role.query.filter_by(name=role_filter).first()
        if role_obj:
            query = query.filter_by(role_id=role_obj.id)
    users_list = query.order_by(User.created_at.desc()).paginate(
        page=page, per_page=25, error_out=False
    )
    roles = Role.query.all()
    agents = User.query.filter(User.role.has(name='agent')).all()
    return render_template('admin/users.html',
        users=users_list, roles=roles, agents=agents)

@admin_bp.route('/users/view/<int:user_id>')
@admin_required
def view_user(user_id):
    user = User.query.get_or_404(user_id)
    return render_template('admin/user_view.html', user=user)

@admin_bp.route('/users/create', methods=['GET', 'POST'])
@admin_required
def create_user():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        role_id = request.form.get('role_id', type=int)
        agent_id = request.form.get('agent_id', type=int)
        name = request.form.get('name')
        company = request.form.get('company')
        country = request.form.get('country')
        sms_limit = request.form.get('sms_limit', 0, type=int)
        if not username or not email or not password:
            flash('Username, email, and password are required.', 'danger')
            return redirect(url_for('admin.create_user'))
        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
            return redirect(url_for('admin.create_user'))
        role = Role.query.get(role_id)
        if not role:
            flash('Invalid role selected.', 'danger')
            return redirect(url_for('admin.create_user'))
        user = User(
            username=username,
            email=email,
            role=role,
            name=name,
            company=company,
            country=country,
            agent_id=agent_id if agent_id else None,
            sms_limit=sms_limit,
            is_active=True
        )
        user.set_password(password)
        user.generate_api_token()
        db.session.add(user)
        db.session.commit()
        ActivityLog.log(
            current_user.id,
            'admin_create_user',
            f'Created user {username} with role {role.display_name}',
            ip_address=request.remote_addr
        )
        flash(f'User {username} created successfully.', 'success')
        return redirect(url_for('admin.users'))
    roles = Role.query.all()
    agents = User.query.filter(User.role.has(name='agent')).all()
    return render_template('admin/user_form.html', roles=roles, agents=agents, user=None)

@admin_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    if request.method == 'POST':
        user.email = request.form.get('email')
        user.name = request.form.get('name')
        user.company = request.form.get('company')
        user.country = request.form.get('country')
        user.skype = request.form.get('skype')
        user.contact = request.form.get('contact')
        user.sms_limit = request.form.get('sms_limit', 0, type=int)
        user.agent_id = request.form.get('agent_id', type=int) or None
        role_id = request.form.get('role_id', type=int)
        if role_id:
            user.role_id = role_id
        user.is_active = bool(request.form.get('is_active'))
        new_password = request.form.get('password')
        if new_password and len(new_password) >= 6:
            user.set_password(new_password)
        db.session.commit()
        ActivityLog.log(
            current_user.id,
            'admin_edit_user',
            f'Edited user {user.username}',
            ip_address=request.remote_addr
        )
        flash(f'User {user.username} updated.', 'success')
        return redirect(url_for('admin.users'))
    roles = Role.query.all()
    agents = User.query.filter(User.role.has(name='agent')).all()
    return render_template('admin/user_form.html', roles=roles, agents=agents, user=user)

@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('Cannot delete your own account.', 'danger')
        return redirect(url_for('admin.users'))
    username = user.username
    db.session.delete(user)
    db.session.commit()
    ActivityLog.log(current_user.id, 'admin_delete_user', f'Deleted user {username}', ip_address=request.remote_addr)
    flash(f'User {username} deleted.', 'success')
    return redirect(url_for('admin.users'))

@admin_bp.route('/users/<int:user_id>/toggle-status', methods=['POST'])
@admin_required
def toggle_user_status(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        return jsonify({'error': 'Cannot toggle own status'}), 400
    user.is_active = not user.is_active
    db.session.commit()
    return jsonify({'success': True, 'is_active': user.is_active})

# ============ SMS RANGES ============

@admin_bp.route('/ranges')
@admin_required
def sms_ranges():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    query = SMDRange.query
    if search:
        query = query.filter(
            db.or_(
                SMDRange.prefix.like(f'%{search}%'),
                SMDRange.country.like(f'%{search}%')
            )
        )
    ranges_list = query.order_by(SMDRange.country).paginate(
        page=page, per_page=25, error_out=False
    )
    return render_template('admin/sms_ranges.html', ranges=ranges_list)

@admin_bp.route('/ranges/create', methods=['GET', 'POST'])
@admin_required
def create_sms_range():
    if request.method == 'POST':
        name = request.form.get('name')
        prefix = request.form.get('prefix')
        country = request.form.get('country')
        test_number = request.form.get('test_number')
        application = request.form.get('application', '')
        daily_limit = request.form.get('daily_limit', 50, type=int)
        payout = request.form.get('payout', 0.0, type=float)
        csv_file = request.files.get('csv_file')
        csv_numbers = []
        if csv_file and csv_file.filename:
            try:
                raw = csv_file.read()
                try:
                    content = raw.decode('utf-8')
                except UnicodeDecodeError:
                    content = raw.decode('latin-1')
                lines = content.strip().split('\n')
                for line in lines:
                    cell = line.split(',')[0].strip()
                    if cell:
                        csv_numbers.append(cell)
            except Exception as e:
                flash(f'Error reading file: {str(e)}', 'danger')
                return redirect(url_for('admin.create_sms_range'))
        sms_range = SMDRange(
            name=name,
            prefix=prefix,
            country=country,
            test_number=test_number,
            application=application if application else None,
            daily_limit=daily_limit,
            payout=payout,
            cost_per_sms=0.005,
            is_active=True
        )
        db.session.add(sms_range)
        db.session.commit()
        created_count = 0
        skip_count = 0
        if csv_numbers:
            existing_numbers = set(
                num[0] for num in db.session.query(SMSNumber.number).all()
            )
            for num_str in csv_numbers:
                num_clean = num_str.strip()
                if not num_clean:
                    continue
                if not num_clean.startswith(prefix):
                    num_clean = f"{prefix}{num_clean}"
                if num_clean in existing_numbers:
                    skip_count += 1
                    continue
                num = SMSNumber(
                    range_id=sms_range.id,
                    number=num_clean,
                    prefix=prefix,
                    status='available',
                    is_active=True
                )
                db.session.add(num)
                created_count += 1
                existing_numbers.add(num_clean)
            db.session.commit()
        ActivityLog.log(
            current_user.id,
            'admin_create_range',
            f'Created range {prefix} and added {created_count} numbers',
            ip_address=request.remote_addr
        )
        result_msg = f'Range {prefix} created with {created_count} numbers.'
        if skip_count > 0:
            result_msg += f' ({skip_count} skipped - already exist)'
        flash(result_msg, 'success')
        return redirect(url_for('admin.sms_ranges'))
    return render_template('admin/range_form.html', range_obj=None)

@admin_bp.route('/ranges/<int:range_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_sms_range(range_id):
    range_obj = SMDRange.query.get_or_404(range_id)
    if request.method == 'POST':
        range_obj.name = request.form.get('name')
        range_obj.prefix = request.form.get('prefix')
        range_obj.country = request.form.get('country')
        range_obj.application = request.form.get('application') or None
        range_obj.operator = request.form.get('operator')
        range_obj.network_type = request.form.get('network_type')
        range_obj.mcc = request.form.get('mcc')
        range_obj.mnc = request.form.get('mnc')
        range_obj.daily_limit = request.form.get('daily_limit', 50, type=int)
        range_obj.payout = request.form.get('payout', 0.0, type=float)
        range_obj.cost_per_sms = request.form.get('cost_per_sms', 0.005, type=float)
        range_obj.currency = request.form.get('currency', 'USD')
        range_obj.rate = request.form.get('rate', 0.0, type=float)
        range_obj.test_number = request.form.get('test_number')
        range_obj.memo = request.form.get('memo')
        range_obj.is_active = bool(request.form.get('is_active'))
        db.session.commit()
        ActivityLog.log(
            current_user.id,
            'admin_edit_range',
            f'Edited range {range_obj.prefix}',
            ip_address=request.remote_addr
        )
        flash(f'Range {range_obj.prefix} updated.', 'success')
        return redirect(url_for('admin.sms_ranges'))
    return render_template('admin/range_form.html', range_obj=range_obj)

@admin_bp.route('/ranges/<int:range_id>/delete', methods=['GET', 'POST'])
@admin_required
def delete_sms_range(range_id):
    range_obj = SMDRange.query.get_or_404(range_id)
    SMSNumber.query.filter_by(range_id=range_id).delete()
    range_info = f'{range_obj.name or range_obj.prefix} - {range_obj.country}'
    db.session.delete(range_obj)
    db.session.commit()
    ActivityLog.log(
        current_user.id,
        'admin_delete_range',
        f'Deleted range {range_info}',
        ip_address=request.remote_addr
    )
    flash(f'Range {range_info} deleted.', 'success')
    return redirect(url_for('admin.sms_ranges'))

# ============ SMS NUMBERS ============

@admin_bp.route('/sms/numbers')
@admin_required
def sms_numbers():
    per_page = request.args.get('per_page', 50, type=int)
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    agent_filter = request.args.get('agent', '')
    query = SMSNumber.query
    if search:
        query = query.filter(SMSNumber.number.like(f'%{search}%'))
    if agent_filter == 'none':
        query = query.filter(SMSNumber.agent_id.is_(None))
    elif agent_filter:
        query = query.filter_by(agent_id=agent_filter)
    if per_page == 99999:
        all_numbers = query.order_by(SMSNumber.created_at.desc()).all()
        class FakePaginate:
            def __init__(self, items):
                self.items = items
                self.total = len(items)
                self.page = 1
                self.pages = 1
                self.has_prev = False
                self.has_next = False
                self.prev_num = None
                self.next_num = None
        numbers = FakePaginate(all_numbers)
    else:
        numbers = query.order_by(SMSNumber.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
    agents = User.query.filter(User.role.has(name='agent')).all()
    return render_template('admin/sms_numbers.html',
        numbers=numbers, agents=agents, per_page=per_page)

@admin_bp.route('/sms/numbers/bulk-delete', methods=['POST'])
@admin_required
def bulk_delete_numbers():
    number_ids = request.form.getlist('number_ids')
    if not number_ids:
        flash('No numbers selected!', 'danger')
        return redirect(url_for('admin.sms_numbers'))
    deleted = 0
    for nid in number_ids:
        num = SMSNumber.query.get(int(nid))
        if num:
            db.session.delete(num)
            deleted += 1
    db.session.commit()
    ActivityLog.log(
        current_user.id,
        'admin_bulk_delete_numbers',
        f'Bulk deleted {deleted} numbers',
        ip_address=request.remote_addr
    )
    flash(f'{deleted} numbers permanently deleted!', 'success')
    return redirect(url_for('admin.sms_numbers'))

@admin_bp.route('/sms/numbers/reclaim', methods=['POST'])
@admin_required
def admin_reclaim_numbers():
    number_ids = request.form.getlist('number_ids')
    if not number_ids:
        flash('No numbers selected!', 'danger')
        return redirect(url_for('admin.sms_numbers'))
    done = 0
    for nid in number_ids:
        num = SMSNumber.query.get(int(nid))
        if num and num.agent_id:
            num.agent_id = None
            num.client_id = None
            num.client_payout = 0.0
            num.agent_payout = 0.0
            num.status = 'available'
            num.assigned_at = None
            done += 1
    db.session.commit()
    ActivityLog.log(
        current_user.id,
        'admin_reclaim_numbers',
        f'Reclaimed {done} numbers back to range',
        ip_address=request.remote_addr
    )
    flash(f'{done} numbers reclaimed and returned to range!', 'success')
    return redirect(url_for('admin.sms_numbers'))

@admin_bp.route('/sms/numbers/<int:number_id>/reclaim', methods=['POST'])
@admin_required
def admin_reclaim_single(number_id):
    num = SMSNumber.query.get_or_404(number_id)
    num.agent_id = None
    num.client_id = None
    num.client_payout = 0.0
    num.agent_payout = 0.0
    num.status = 'available'
    num.assigned_at = None
    db.session.commit()
    ActivityLog.log(
        current_user.id,
        'admin_reclaim_single',
        f'Reclaimed number {num.number} back to range',
        ip_address=request.remote_addr
    )
    flash(f'Number {num.number} reclaimed and returned to range!', 'success')
    return redirect(url_for('admin.sms_numbers'))

@admin_bp.route('/sms/numbers/<int:number_id>/delete', methods=['POST'])
@admin_required
def delete_number(number_id):
    number = SMSNumber.query.get_or_404(number_id)
    num_str = number.number
    db.session.delete(number)
    db.session.commit()
    ActivityLog.log(
        current_user.id,
        'admin_delete_number',
        f'Permanently deleted number {num_str}',
        ip_address=request.remote_addr
    )
    flash(f'Number {num_str} permanently deleted.', 'success')
    return redirect(url_for('admin.sms_numbers'))

# ============ SMS CDR ============

@admin_bp.route('/sms/cdr')
@admin_required
def sms_cdr():
    page = request.args.get('page', 1, type=int)
    fdate1 = request.args.get('fdate1', datetime.utcnow().strftime('%Y-%m-%d'))
    fdate2 = request.args.get('fdate2', datetime.utcnow().strftime('%Y-%m-%d'))
    def parse_date(date_str):
        try:
            return datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
            try:
                return datetime.strptime(date_str, '%Y-%m-%d')
            except (ValueError, TypeError):
                return datetime.utcnow()
    date1 = parse_date(fdate1)
    date2 = parse_date(fdate2).replace(hour=23, minute=59, second=59)
    query = SMSCDR.query.filter(
        SMSCDR.created_at >= date1,
        SMSCDR.created_at <= date2
    )
    cdr_records = query.order_by(SMSCDR.created_at.desc()).paginate(
        page=page, per_page=50, error_out=False
    )
    totals = db.session.query(
        db.func.count(SMSCDR.id).label('total'),
        db.func.sum(SMSCDR.profit).label('total_profit')
    ).filter(
        SMSCDR.created_at >= date1,
        SMSCDR.created_at <= date2
    ).first()
    return render_template('admin/sms_cdr.html',
        cdr_records=cdr_records,
        totals=totals,
        fdate1=fdate1,
        fdate2=fdate2
    )

# ============ ACTIVITY LOGS ============

@admin_bp.route('/activity')
@admin_required
def activity_logs():
    page = request.args.get('page', 1, type=int)
    user_filter = request.args.get('user', '')
    action_filter = request.args.get('action', '')
    query = ActivityLog.query
    if user_filter:
        query = query.filter_by(user_id=user_filter)
    if action_filter:
        query = query.filter_by(action=action_filter)
    activities = query.order_by(ActivityLog.created_at.desc()).paginate(
        page=page, per_page=50, error_out=False
    )
    users = User.query.all()
    return render_template('admin/activity.html', activities=activities, users=users)

# ============ NEWS ============

@admin_bp.route('/news')
@admin_required
def news():
    page = request.args.get('page', 1, type=int)
    news_list = News.query.order_by(News.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    return render_template('admin/news.html', news_list=news_list)

@admin_bp.route('/news/create', methods=['GET', 'POST'])
@admin_required
def create_news():
    if request.method == 'POST':
        headline = request.form.get('headline')
        content = request.form.get('content')
        if not headline:
            flash('Headline is required.', 'danger')
            return redirect(url_for('admin.create_news'))
        news_item = News(
            headline=headline,
            content=content,
            created_by=current_user.id,
            is_active=True
        )
        db.session.add(news_item)
        db.session.commit()
        flash('News created.', 'success')
        return redirect(url_for('admin.news'))
    return render_template('admin/news_form.html', news=None)

@admin_bp.route('/news/<int:news_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_news(news_id):
    news_item = News.query.get_or_404(news_id)
    if request.method == 'POST':
        news_item.headline = request.form.get('headline')
        news_item.content = request.form.get('content')
        news_item.is_active = bool(request.form.get('is_active'))
        db.session.commit()
        flash('News updated.', 'success')
        return redirect(url_for('admin.news'))
    return render_template('admin/news_form.html', news=news_item)

@admin_bp.route('/news/<int:news_id>/delete', methods=['POST'])
@admin_required
def delete_news(news_id):
    news_item = News.query.get_or_404(news_id)
    db.session.delete(news_item)
    db.session.commit()
    flash('News deleted.', 'success')
    return redirect(url_for('admin.news'))

# ============ RANGE DAILY LIMIT ============

@admin_bp.route('/agent-limits')
@admin_required
def agent_limits():
    ranges = SMDRange.query.filter_by(is_active=True).order_by(SMDRange.country).all()
    return render_template('admin/agent_limits.html', ranges=ranges)

@admin_bp.route('/agent-limits/set/<int:range_id>', methods=['POST'])
@admin_required
def set_range_limit(range_id):
    sms_range = SMDRange.query.get_or_404(range_id)
    daily_limit = request.form.get('daily_limit', 50, type=int)
    sms_range.daily_limit = daily_limit
    db.session.commit()
    flash(f'{sms_range.country} daily limit set to {daily_limit}!', 'success')
    return redirect(url_for('admin.agent_limits'))

@admin_bp.route('/ranges/set-payout/<int:range_id>', methods=['POST'])
@admin_required
def set_range_payout(range_id):
    sms_range = SMDRange.query.get_or_404(range_id)
    payout = request.form.get('payout', 0.0, type=float)
    sms_range.payout = payout
    db.session.commit()
    flash(f'{sms_range.country} payout set to ${payout:.4f}/OTP!', 'success')
    return redirect(url_for('admin.sms_ranges'))

# ============ AGENT OTP STATS ============

@admin_bp.route('/agent-otp-stats')
@admin_required
def agent_otp_stats():
    from app.models.provider import OTPLog
    today = datetime.utcnow().date()
    week_ago = today - timedelta(days=7)
    first_of_month = today.replace(day=1)

    agents = User.query.filter(User.role.has(name='agent')).all()

    stats = []
    for agent in agents:
        agent_number_ids = [n.id for n in SMSNumber.query.filter_by(agent_id=agent.id).all()]

        if not agent_number_ids:
            stats.append({
                'agent': agent,
                'today': 0,
                'week': 0,
                'month': 0,
                'total': 0
            })
            continue

        today_count = OTPLog.query.filter(
            OTPLog.number_id.in_(agent_number_ids),
            db.func.date(OTPLog.received_at) == today
        ).count()

        week_count = OTPLog.query.filter(
            OTPLog.number_id.in_(agent_number_ids),
            OTPLog.received_at >= week_ago
        ).count()

        month_count = OTPLog.query.filter(
            OTPLog.number_id.in_(agent_number_ids),
            OTPLog.received_at >= first_of_month
        ).count()

        total_count = OTPLog.query.filter(
            OTPLog.number_id.in_(agent_number_ids)
        ).count()

        stats.append({
            'agent': agent,
            'today': today_count,
            'week': week_count,
            'month': month_count,
            'total': total_count
        })

    stats.sort(key=lambda x: x['total'], reverse=True)

    return render_template('admin/agent_otp_stats.html', stats=stats)

# ============ ADD NUMBERS TO AGENT ============

@admin_bp.route('/add-numbers-to-agent', methods=['GET', 'POST'])
@admin_required
def add_numbers_to_agent():
    search = request.args.get('search', '')
    agents_query = User.query.filter(User.role.has(name='agent'))
    if search:
        agents_query = agents_query.filter(
            db.or_(
                User.username.like(f'%{search}%'),
                User.name.like(f'%{search}%')
            )
        )
    agents = agents_query.all()
    ranges = SMDRange.query.filter_by(is_active=True).all()
    if request.method == 'POST':
        agent_id = request.form.get('agent_id', type=int)
        range_id = request.form.get('range_id', type=int)
        count = request.form.get('count', 0, type=int)
        if not agent_id or not range_id or count <= 0:
            flash('All fields are required!', 'danger')
            return redirect(url_for('admin.add_numbers_to_agent'))
        agent = User.query.get(agent_id)
        sms_range = SMDRange.query.get(range_id)
        if not agent or not sms_range:
            flash('Invalid agent or range!', 'danger')
            return redirect(url_for('admin.add_numbers_to_agent'))
        available = SMSNumber.query.filter_by(
            range_id=range_id,
            agent_id=None,
            is_active=True
        ).limit(count).all()
        if not available:
            flash('No available numbers in this range!', 'warning')
            return redirect(url_for('admin.add_numbers_to_agent'))
        added = 0
        for num in available:
            num.agent_id = agent_id
            num.status = 'reserved'
            num.assigned_at = datetime.utcnow()
            added += 1
        db.session.commit()
        ActivityLog.log(
            current_user.id,
            'admin_add_numbers_to_agent',
            f'Added {added} numbers from {sms_range.prefix} to agent {agent.username}',
            ip_address=request.remote_addr
        )
        flash(f'{added} numbers added to {agent.username} successfully!', 'success')
        return redirect(url_for('admin.add_numbers_to_agent'))
    return render_template('admin/add_numbers_to_agent.html',
        agents=agents, ranges=ranges, search=search)

# ============ AGENT ROUTES ============

@admin_bp.route('/agent/add-numbers', methods=['GET', 'POST'])
@login_required
def agent_add_numbers():
    if not (current_user.is_agent() or current_user.is_admin()):
        flash('Access denied.', 'danger')
        return redirect(url_for('main.dashboard'))
    if request.method == 'POST':
        range_id = request.form.get('range_id', type=int)
        numbers_count = request.form.get('numbers_count', 0, type=int)
        if not range_id:
            flash('Please select a range.', 'danger')
            return redirect(url_for('admin.agent_add_numbers'))
        sms_range = SMDRange.query.get(range_id)
        if not sms_range:
            flash('Invalid range.', 'danger')
            return redirect(url_for('admin.agent_add_numbers'))
        if sms_range.daily_limit > 0:
            today_taken = SMSNumber.query.filter(
                SMSNumber.agent_id == current_user.id,
                SMSNumber.range_id == range_id,
                db.func.date(SMSNumber.assigned_at) == date.today()
            ).count()
            daily_remaining = sms_range.daily_limit - today_taken
            if daily_remaining <= 0:
                flash(f'Daily limit reached! Limit: {sms_range.daily_limit}/day', 'danger')
                return redirect(url_for('admin.agent_add_numbers'))
            numbers_count = min(numbers_count, daily_remaining)
        available_numbers = SMSNumber.query.filter_by(
            range_id=range_id,
            agent_id=None,
            is_active=True
        ).limit(numbers_count).all()
        if not available_numbers:
            flash('No available numbers in this range.', 'warning')
            return redirect(url_for('admin.agent_add_numbers'))
        numbers_added = 0
        for num in available_numbers:
            num.agent_id = current_user.id
            num.status = 'reserved'
            num.assigned_at = datetime.utcnow()
            numbers_added += 1
        db.session.commit()
        ActivityLog.log(
            current_user.id,
            'agent_add_numbers',
            f'Added {numbers_added} numbers from range {sms_range.prefix}',
            ip_address=request.remote_addr
        )
        flash(f'{numbers_added} numbers added successfully!', 'success')
        return redirect(url_for('admin.agent_my_numbers'))

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)
    search = request.args.get('search', '')
    ranges_query = SMDRange.query.filter_by(is_active=True)
    if search:
        ranges_query = ranges_query.filter(
            db.or_(
                SMDRange.name.like(f'%{search}%'),
                SMDRange.country.like(f'%{search}%'),
                SMDRange.prefix.like(f'%{search}%')
            )
        )
    ranges_query = ranges_query.order_by(SMDRange.country)

    if per_page == 99999:
        all_ranges = ranges_query.all()
        class FakePaginate:
            def __init__(self, items):
                self.items = items
                self.total = len(items)
                self.page = 1
                self.pages = 1
                self.has_prev = False
                self.has_next = False
                self.prev_num = None
                self.next_num = None
        ranges = FakePaginate(all_ranges)
    else:
        ranges = ranges_query.paginate(page=page, per_page=per_page, error_out=False)

    current_numbers = SMSNumber.query.filter_by(agent_id=current_user.id).count()
    return render_template('admin/agent_add_numbers.html',
        ranges=ranges,
        current_numbers=current_numbers,
        per_page=per_page
    )

@admin_bp.route('/agent/my-numbers')
@login_required
def agent_my_numbers():
    if not (current_user.is_agent() or current_user.is_admin()):
        flash('Access denied.', 'danger')
        return redirect(url_for('main.dashboard'))
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)
    search = request.args.get('search', '')
    frange = request.args.get('frange', '')
    fclient = request.args.get('fclient', '')
    query = SMSNumber.query.filter_by(agent_id=current_user.id)
    if search:
        query = query.filter(SMSNumber.number.like(f'%{search}%'))
    if frange:
        query = query.filter_by(range_id=frange)
    if fclient == 'none':
        query = query.filter(SMSNumber.client_id.is_(None))
    elif fclient:
        query = query.filter_by(client_id=fclient)
    if per_page == 99999:
        all_numbers = query.order_by(SMSNumber.number).all()
        class FakePaginate:
            def __init__(self, items):
                self.items = items
                self.total = len(items)
                self.page = 1
                self.pages = 1
                self.has_prev = False
                self.has_next = False
                self.prev_num = None
                self.next_num = None
        numbers = FakePaginate(all_numbers)
    else:
        numbers = query.order_by(SMSNumber.number).paginate(
            page=page, per_page=per_page, error_out=False
        )
    total_numbers = SMSNumber.query.filter_by(agent_id=current_user.id).count()
    assigned_count = SMSNumber.query.filter(
        SMSNumber.agent_id == current_user.id,
        SMSNumber.client_id.isnot(None)
    ).count()
    free_count = total_numbers - assigned_count
    range_ids = [
        r[0] for r in db.session.query(SMSNumber.range_id)
        .filter(SMSNumber.agent_id == current_user.id, SMSNumber.range_id.isnot(None))
        .distinct().all()
    ]
    ranges = SMDRange.query.filter(SMDRange.id.in_(range_ids)).all() if range_ids else []
    clients = User.query.filter_by(agent_id=current_user.id).all()
    return render_template('admin/agent_my_numbers.html',
        numbers=numbers,
        total_numbers=total_numbers,
        assigned_count=assigned_count,
        free_count=free_count,
        ranges=ranges,
        clients=clients,
        per_page=per_page
    )

@admin_bp.route('/agent/bulk-assign', methods=['POST'])
@login_required
def agent_bulk_assign():
    if not (current_user.is_agent() or current_user.is_admin()):
        flash('Access denied.', 'danger')
        return redirect(url_for('main.dashboard'))
    number_ids = request.form.getlist('number_ids')
    client_id = request.form.get('client_id', type=int)
    client_payout = request.form.get('client_payout', 0.0, type=float)
    if not number_ids:
        flash('No numbers selected!', 'danger')
        return redirect(url_for('admin.agent_my_numbers'))
    if not client_id:
        flash('Please select a client!', 'danger')
        return redirect(url_for('admin.agent_my_numbers'))
    client = User.query.get(client_id)
    if not client or client.agent_id != current_user.id:
        flash('Invalid client!', 'danger')
        return redirect(url_for('admin.agent_my_numbers'))
    assigned = 0
    skipped = 0
    for nid in number_ids:
        num = SMSNumber.query.get(int(nid))
        if num and num.agent_id == current_user.id:
            if num.client_id and num.client_id != client_id:
                skipped += 1
                continue
            num.client_id = client_id
            num.client_payout = client_payout
            num.status = 'activated'
            num.assigned_at = datetime.utcnow()
            assigned += 1
    db.session.commit()
    msg = f'{assigned} numbers assigned to {client.username} at ${client_payout}/OTP!'
    if skipped > 0:
        msg += f' ({skipped} skipped — already assigned to another client)'
    flash(msg, 'success')
    return redirect(url_for('admin.agent_my_numbers'))

@admin_bp.route('/agent/bulk-unassign', methods=['POST'])
@login_required
def agent_bulk_unassign():
    if not (current_user.is_agent() or current_user.is_admin()):
        flash('Access denied.', 'danger')
        return redirect(url_for('main.dashboard'))
    number_ids = request.form.getlist('number_ids')
    if not number_ids:
        flash('No numbers selected!', 'danger')
        return redirect(url_for('admin.agent_my_numbers'))
    done = 0
    for nid in number_ids:
        num = SMSNumber.query.get(int(nid))
        if num and num.agent_id == current_user.id:
            num.client_id = None
            num.client_payout = 0.0
            num.status = 'reserved'
            done += 1
    db.session.commit()
    flash(f'{done} numbers unassigned!', 'success')
    return redirect(url_for('admin.agent_my_numbers'))

@admin_bp.route('/agent/return-numbers', methods=['POST'])
@login_required
def agent_return_numbers():
    if not (current_user.is_agent() or current_user.is_admin()):
        flash('Access denied.', 'danger')
        return redirect(url_for('main.dashboard'))
    number_ids = request.form.getlist('number_ids')
    if not number_ids:
        flash('No numbers selected!', 'danger')
        return redirect(url_for('admin.agent_my_numbers'))
    done = 0
    for nid in number_ids:
        num = SMSNumber.query.get(int(nid))
        if num and num.agent_id == current_user.id:
            num.agent_id = None
            num.client_id = None
            num.client_payout = 0.0
            num.agent_payout = 0.0
            num.status = 'available'
            num.assigned_at = None
            done += 1
    db.session.commit()
    flash(f'{done} numbers returned to range!', 'success')
    return redirect(url_for('admin.agent_my_numbers'))

@admin_bp.route('/agent/download-numbers', methods=['POST'])
@login_required
def agent_download_numbers():
    number_ids = request.form.getlist('number_ids')
    if number_ids:
        numbers = SMSNumber.query.filter(
            SMSNumber.id.in_([int(x) for x in number_ids]),
            SMSNumber.agent_id == current_user.id
        ).all()
    else:
        numbers = SMSNumber.query.filter_by(agent_id=current_user.id).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Number', 'Range', 'Client', 'Status', 'OTP Price', 'Assigned At'])
    for num in numbers:
        writer.writerow([
            num.number,
            f"+{num.sms_range.prefix} - {num.sms_range.country}" if num.sms_range else '',
            num.client.username if num.client else 'Unassigned',
            num.status,
            num.client_payout,
            num.assigned_at.strftime('%Y-%m-%d %H:%M') if num.assigned_at else ''
        ])
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=numbers.csv'}
    )

@admin_bp.route('/agent/create-client', methods=['GET', 'POST'])
@login_required
def agent_create_client():
    if not (current_user.is_agent() or current_user.is_admin()):
        flash('Access denied.', 'danger')
        return redirect(url_for('main.dashboard'))
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        name = request.form.get('name')
        company = request.form.get('company')
        country = request.form.get('country')
        if not username or not email or not password:
            flash('Username, email, and password are required.', 'danger')
            return redirect(url_for('admin.agent_create_client'))
        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
            return redirect(url_for('admin.agent_create_client'))
        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'danger')
            return redirect(url_for('admin.agent_create_client'))
        client_role = Role.query.filter_by(name='client').first()
        if not client_role:
            flash('Client role not found.', 'danger')
            return redirect(url_for('admin.agent_create_client'))
        client = User(
            username=username,
            email=email,
            role_id=client_role.id,
            name=name,
            company=company,
            country=country,
            agent_id=current_user.id,
            is_active=True
        )
        client.set_password(password)
        client.generate_api_token()
        db.session.add(client)
        db.session.commit()
        ActivityLog.log(
            current_user.id,
            'agent_create_client',
            f'Created client {username}',
            ip_address=request.remote_addr
        )
        flash(f'Client {username} created successfully!', 'success')
        return redirect(url_for('admin.agent_clients'))
    return render_template('admin/agent_create_client.html')

@admin_bp.route('/agent/clients')
@login_required
def agent_clients():
    if not (current_user.is_agent() or current_user.is_admin()):
        flash('Access denied.', 'danger')
        return redirect(url_for('main.dashboard'))
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    query = User.query.filter_by(agent_id=current_user.id)
    if search:
        query = query.filter(
            db.or_(
                User.username.like(f'%{search}%'),
                User.email.like(f'%{search}%'),
                User.name.like(f'%{search}%')
            )
        )
    clients = query.order_by(User.created_at.desc()).paginate(
        page=page, per_page=25, error_out=False
    )
    return render_template('admin/agent_clients.html', clients=clients)