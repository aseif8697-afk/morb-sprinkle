#!/usr/bin/env python3

from app import create_app, db
from app.models.user import User, Role
from app.models.sms import SMDRange, SMSNumber, SMSCDR
from app.models.activity import ActivityLog, News
import os

app = create_app()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()

        admin_role = Role.query.filter_by(name='admin').first()
        if not admin_role:
            admin_role = Role(name='admin', display_name='Administrator')
            db.session.add(admin_role)

        agent_role = Role.query.filter_by(name='agent').first()
        if not agent_role:
            agent_role = Role(name='agent', display_name='Agent')
            db.session.add(agent_role)

        client_role = Role.query.filter_by(name='client').first()
        if not client_role:
            client_role = Role(name='client', display_name='Client')
            db.session.add(client_role)

        db.session.commit()

        admin_user = User.query.filter_by(username='admin').first()
        if not admin_user:
            admin_user = User(
                username='admin',
                email='admin@elking-sms.com',
                role=admin_role,
                is_active=True
            )
            admin_user.set_password('SEIFELKING123')
            db.session.add(admin_user)
            db.session.commit()
            print("Default admin user created: admin / SEIFELKING123")

        agent = User.query.filter_by(username='agent1').first()
        if not agent:
            agent = User(
                username='agent1',
                email='agent1@elking-sms.com',
                role=agent_role,
                is_active=True
            )
            agent.set_password('agent123')
            db.session.add(agent)
            db.session.commit()
            print("Sample agent created: agent1 / agent123")

        if SMDRange.query.count() == 0:
            sample_ranges = [
                SMDRange(prefix='1', country='United States', operator='AT&T', network_type='GSM', hlr_lookup=True, mcc='310', mnc='410', cost_per_sms=0.0050),
                SMDRange(prefix='44', country='United Kingdom', operator='Vodafone', network_type='GSM', hlr_lookup=True, mcc='234', mnc='15', cost_per_sms=0.0045),
                SMDRange(prefix='49', country='Germany', operator='Deutsche Telekom', network_type='GSM', hlr_lookup=True, mcc='262', mnc='1', cost_per_sms=0.0048),
                SMDRange(prefix='33', country='France', operator='Orange', network_type='GSM', hlr_lookup=True, mcc='208', mnc='1', cost_per_sms=0.0045),
                SMDRange(prefix='91', country='India', operator='Airtel', network_type='GSM', hlr_lookup=True, mcc='404', mnc='40', cost_per_sms=0.0030),
            ]
            for r in sample_ranges:
                db.session.add(r)
            db.session.commit()
            print(f"{len(sample_ranges)} sample SMS ranges added")

        print("ELKING SMS is ready!")

    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)