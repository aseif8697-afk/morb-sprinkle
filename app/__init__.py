import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_bcrypt import Bcrypt
from flask_cors import CORS
from config import config

db = SQLAlchemy()
login_manager = LoginManager()
bcrypt = Bcrypt()

def create_app(config_name='default'):
    app = Flask(__name__)
    app.config.from_object(config[config_name])

    db.init_app(app)
    login_manager.init_app(app)
    bcrypt.init_app(app)
    CORS(app)

    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please login to continue.'
    login_manager.login_message_category = 'warning'

    from app.models.user import User
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    from app.routes.auth import auth_bp
    from app.routes.main import main_bp
    from app.routes.admin import admin_bp
    from app.routes.developer import dev_bp
    from app.routes.sms_monitor import monitor_bp
    from app.routes.provider import provider_bp
    from app.routes.billing import billing_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(dev_bp)
    app.register_blueprint(monitor_bp)
    app.register_blueprint(provider_bp)
    app.register_blueprint(billing_bp)

    with app.app_context():
        db.create_all()

        from app.models.user import User, Role
        from app.models.sms import AgentRangeLimit
        from app.models.wallet import Wallet, WithdrawalRequest
        from app.models.billing import AgentBankAccount, CreditNote

        # Roles create
        for role_name, display in [
            ('admin', 'Administrator'),
            ('agent', 'Agent'),
            ('client', 'Client'),
            ('developer', 'Developer')
        ]:
            if not Role.query.filter_by(name=role_name).first():
                db.session.add(Role(name=role_name, display_name=display))
        db.session.commit()

        # Auto create admin
        admin_role = Role.query.filter_by(name='admin').first()
        if not User.query.filter_by(username='admin').first():
            admin = User(
                username='admin',
                email='morb.owner@gmail.com',
                password_hash=bcrypt.generate_password_hash('seifamr555').decode('utf-8'),
                role=admin_role,
                is_active=True
            )
            db.session.add(admin)
            db.session.commit()

        from app.fetcher import start_all_providers
        start_all_providers(app)

    # ---- Weekly Credit Note auto-generator (APScheduler) ----
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true' or not app.debug:
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from app.scheduler_jobs import generate_weekly_credit_notes

            scheduler = BackgroundScheduler(daemon=True)
            scheduler.add_job(
                func=lambda: generate_weekly_credit_notes(app),
                trigger='interval',
                hours=24,
                id='weekly_credit_note_job',
                replace_existing=True
            )
            scheduler.start()
        except Exception as e:
            print(f'Scheduler failed to start: {e}')

    return app

app = create_app()
