#!/usr/bin/env python3

import os
from pathlib import Path

# Keep the existing application package available as `app.*` while exposing
# the Flask entry point from this file for Vercel and Gunicorn.
__path__ = [str(Path(__file__).resolve().parent / 'app')]

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
    flask_app = Flask(__name__)
    flask_app.config.from_object(config[config_name])

    db.init_app(flask_app)
    login_manager.init_app(flask_app)
    bcrypt.init_app(flask_app)
    CORS(flask_app)

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

    flask_app.register_blueprint(auth_bp)
    flask_app.register_blueprint(main_bp)
    flask_app.register_blueprint(admin_bp)
    flask_app.register_blueprint(dev_bp)
    flask_app.register_blueprint(monitor_bp)
    flask_app.register_blueprint(provider_bp)
    flask_app.register_blueprint(billing_bp)

    with flask_app.app_context():
        db.create_all()

        from app.models.user import User, Role
        from app.models.sms import AgentRangeLimit
        from app.models.wallet import Wallet, WithdrawalRequest
        from app.models.billing import AgentBankAccount, CreditNote

        for role_name, display in [
            ('admin', 'Administrator'),
            ('agent', 'Agent'),
            ('client', 'Client'),
            ('developer', 'Developer')
        ]:
            if not Role.query.filter_by(name=role_name).first():
                db.session.add(Role(name=role_name, display_name=display))
        db.session.commit()

        admin_role = Role.query.filter_by(name='admin').first()
        if not User.query.filter_by(username='admin').first():
            admin = User(
                username='admin',
                email='admin@panel.com',
                password_hash=bcrypt.generate_password_hash('SEIFELKING123').decode('utf-8'),
                role=admin_role,
                is_active=True
            )
            db.session.add(admin)
            db.session.commit()

        from app.fetcher import start_all_providers
        start_all_providers(flask_app)

    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true' or not flask_app.debug:
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from app.scheduler_jobs import generate_weekly_credit_notes

            scheduler = BackgroundScheduler(daemon=True)
            scheduler.add_job(
                func=lambda: generate_weekly_credit_notes(flask_app),
                trigger='interval',
                hours=24,
                id='weekly_credit_note_job',
                replace_existing=True
            )
            scheduler.start()
        except Exception as e:
            print(f'Scheduler failed to start: {e}')

    return flask_app


# Vercel/Gunicorn look for this WSGI variable.
app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
