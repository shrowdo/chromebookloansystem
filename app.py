from flask import Flask
from dotenv import load_dotenv

load_dotenv()

# Import the os module
import os

# Retrieve the admin password from environment variables
admin_password = os.environ.get('ADMIN_PASSWORD')

from flask import render_template, request, redirect, url_for, abort, flash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime, timedelta
from sqlalchemy.dialects.postgresql import JSON
from urllib.parse import quote
from nameparser import HumanName
from pytz import timezone
import psycopg2
import re
import logging
import sys
from flask_mail import Mail, Message
from flask import jsonify

logging.basicConfig(stream=sys.stdout, level=logging.INFO, format='%(asctime)s - %(message)s')

app = Flask(__name__)

mail = Mail(app)
app.config['MAIL_SERVER'] = 'smtp.office365.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False
mail.init_app(app)

if os.environ.get('FLASK_ENV') == 'development':
    app.config.from_object('config.DevelopmentConfig')
else:
    app.config.from_object('config.ProductionConfig')

database_url = app.config['SQLALCHEMY_DATABASE_URI']

if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url

db = SQLAlchemy(app)
migrate = Migrate(app, db)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    chromebooks = db.relationship('Chromebook', backref='user', lazy=True)

def default_history():
    return []

class Chromebook(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    identifier = db.Column(db.String(80), unique=True, nullable=False)
    serial_number = db.Column(db.String(80), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    loaned_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(80), default='Available', nullable=False)
    history = db.relationship('ChromebookHistory', backref='chromebook', lazy=True, cascade="all, delete")
    email_sent = db.Column(db.Boolean, default=False, nullable=False)
    
class ChromebookHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chromebook_id = db.Column(db.Integer, db.ForeignKey('chromebook.id', ondelete='CASCADE'), nullable=False)
    username = db.Column(db.String(80), nullable=False)
    action_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    action = db.Column(db.String(80), nullable=False)  # Can be 'Loaned' or 'Returned'

@app.route('/')
def home():
    chromebooks = Chromebook.query.filter_by(status='Available').all()
    chromebooks.sort(key=lambda x: int(x.identifier))

    loaned_chromebooks = Chromebook.query.filter(Chromebook.status=='Loaned').all()
    loaned_chromebooks.sort(key=lambda x: int(x.identifier))

    return render_template('home.html', chromebooks=chromebooks, loaned_chromebooks=loaned_chromebooks)

@app.route('/loan', methods=['POST'])
def loan_chromebook():
    username = request.form.get('username')
    chromebook_id = request.form.get('chromebook_id')

    user = User.query.filter_by(username=username).first()
    if not user:
        user = User(username=username)
        db.session.add(user)
        db.session.commit()

    chromebook = Chromebook.query.get(chromebook_id)
    if chromebook.status == 'Loaned':
        return jsonify({'success': False, 'message': 'Chromebook is already loaned.'}), 400
    elif chromebook.status == 'Missing':
        return jsonify({'success': False, 'message': 'Chromebook is marked as missing and cannot be loaned.'}), 400

    chromebook.status = 'Loaned'
    chromebook.user_id = user.id
    chromebook.loaned_at = datetime.utcnow()
    chromebook.email_sent = False
    
    history_entry = ChromebookHistory(chromebook_id=chromebook.id, username=user.username, action='Loaned')
    db.session.add(history_entry)

    if len(chromebook.history) > 6:
        oldest_entry = ChromebookHistory.query.filter_by(chromebook_id=chromebook.id).order_by(ChromebookHistory.action_date).first()
        db.session.delete(oldest_entry)

    db.session.commit()
    return jsonify({'success': True, 'message': f'Device {chromebook.identifier} Loaned. Thank You. Please return by 4pm'}), 200

def datetimefilter(value, format='%Y-%m-%d %H:%M:%S'):
    utc = timezone('UTC')
    london_tz = timezone('Europe/London')
    value = utc.localize(value)
    return value.astimezone(london_tz).strftime(format)

app.jinja_env.filters['datetimefilter'] = datetimefilter

@app.route('/return', methods=['POST'])
def return_chromebook():
    chromebook_id = request.form.get('chromebook_id')
    chromebook = Chromebook.query.get(chromebook_id)

    if chromebook and chromebook.status == 'Loaned':
        user = User.query.get(chromebook.user_id)
        chromebook.status = 'Available'
        chromebook.user_id = None
        chromebook.loaned_at = None
        chromebook.email_sent = False

        history_entry = ChromebookHistory(chromebook_id=chromebook.id, username=user.username, action='Returned')
        db.session.add(history_entry)

        if len(chromebook.history) > 6:
            oldest_entry = ChromebookHistory.query.filter_by(chromebook_id=chromebook.id).order_by(ChromebookHistory.action_date).first()
            db.session.delete(oldest_entry)

        db.session.commit()
        return jsonify({'success': True, 'message': 'Thank you!'}), 200
    else:
        return jsonify({'success': False, 'message': 'Chromebook is not currently loaned.'}), 400

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    filter_by = request.args.get('filter', 'all')

    if request.method == 'POST':
        password = request.form.get('password')
        if password != admin_password:
            flash('Incorrect password. Please try again.')
            return redirect(url_for('home'))

    users = User.query.all()
    now = datetime.utcnow()

    chromebooks = Chromebook.query
    if filter_by == 'all':
        chromebooks = chromebooks.all()
    elif filter_by == 'available':
        chromebooks = chromebooks.filter_by(status='Available').all()
    elif filter_by == 'loaned':
        chromebooks = chromebooks.filter_by(status='Loaned').all()
    elif filter_by == 'overdue':
        chromebooks = chromebooks.filter(Chromebook.status == 'Loaned', now - Chromebook.loaned_at > timedelta(hours=24)).all()
    elif filter_by == 'missing':
        chromebooks = chromebooks.filter_by(status='Missing').all()

    chromebooks = sorted(chromebooks, key=lambda cb: int(cb.identifier))  

    overdue_chromebook_emails = [chromebook.user.username + ('' if '@tiffingirls.org' in chromebook.user.username else '@tiffingirls.org') for chromebook in chromebooks if chromebook.status == 'Loaned' and chromebook.email_sent == False and (now - chromebook.loaned_at > timedelta(hours=24))]

    overdue_chromebook_usernames = [re.sub(r'^\d{2}|@tiffingirls.org$', '', chromebook.user.username) for chromebook in chromebooks if chromebook.status == 'Loaned' and (now - chromebook.loaned_at > timedelta(hours=24))]
    overdue_chromebook_names = [f'{username[0].upper()} {username[1:].capitalize()}' for username in overdue_chromebook_usernames]

    reception_email = "reception@tiffingirls.org"
    reception_subject = quote("Overdue Chromebook Report")
    reception_body = quote(f"Dear Reception,\n\nThe following users have Chromebooks that are overdue for return:\n\n" + "\n".join(overdue_chromebook_names) + "\n\nPlease follow up with them.\n\nThank you.")
    reception_mailto_link = f'mailto:{reception_email}?subject={reception_subject}&body={reception_body}'
    
    available_count = Chromebook.query.filter_by(status='Available').count()
    loaned_count = Chromebook.query.filter_by(status='Loaned').count()
    missing_count = Chromebook.query.filter_by(status='Missing').count()
    overdue_count = Chromebook.query.filter(Chromebook.status == 'Loaned', now - Chromebook.loaned_at > timedelta(hours=24)).count()
    total_chromebooks = Chromebook.query.count()
    
    return render_template('admin.html', chromebooks=chromebooks, users=users, reception_mailto_link=reception_mailto_link, now=now, timedelta=timedelta, available_count=available_count, loaned_count=loaned_count, overdue_count=overdue_count, missing_count=missing_count, total_chromebooks=total_chromebooks)

@app.route('/prepare_overdue_emails')
def prepare_overdue_emails():
    # Mark the Chromebooks as having an email sent
    now = datetime.utcnow()
    overdue_chromebooks = Chromebook.query.filter(
        Chromebook.status == 'Loaned',
        now - Chromebook.loaned_at > timedelta(hours=24),
        Chromebook.email_sent == False
    ).all()

    for chromebook in overdue_chromebooks:
        chromebook.email_sent = True
    db.session.commit()

    # Redirect to the mailto link
    overdue_chromebook_emails = [
        chromebook.user.username + ('' if '@tiffingirls.org' in chromebook.user.username else '@tiffingirls.org')
        for chromebook in overdue_chromebooks
    ]
    subject = quote("Overdue Chromebook Reminder")
    body = quote("Dear User,\n\nOur records indicate that you have a Chromebook that is overdue for return. Please return it as soon as possible.\n\nThank you.")
    mailto_link = f'mailto:{";".join(overdue_chromebook_emails)}?subject={subject}&body={body}'
    return redirect(mailto_link)

@app.route('/add_chromebook', methods=['POST'])
def add_chromebook():
    identifier = request.form.get('identifier')
    serial_number = request.form.get('serial_number')
    
    if identifier and serial_number:
        chromebook = Chromebook(identifier=identifier, serial_number=serial_number)
        db.session.add(chromebook)
        db.session.commit()
    
    return redirect(url_for('admin'))

@app.route('/edit_chromebook/<int:chromebook_id>', methods=['POST'])
def edit_chromebook(chromebook_id):
    chromebook = Chromebook.query.get(chromebook_id)
    if not chromebook:
        abort(404)
    chromebook.identifier = request.form.get('identifier')
    chromebook.serial_number = request.form.get('serial_number')
    db.session.commit()
    return redirect(url_for('admin'))

@app.route('/delete_chromebook/<int:chromebook_id>', methods=['POST'])
def delete_chromebook(chromebook_id):
    chromebook = Chromebook.query.get_or_404(chromebook_id)
    
    db.session.delete(chromebook)
    db.session.commit()
    return redirect(url_for('admin'))

@app.route('/mark_missing/<int:chromebook_id>', methods=['POST'])
def mark_missing(chromebook_id):
    chromebook = Chromebook.query.get(chromebook_id)
    if chromebook:
        if chromebook.status == 'Loaned':
            flash(f'Chromebook {chromebook.identifier} is currently loaned and cannot be marked as missing.', 'danger')
        else:
            chromebook.status = 'Missing'
            db.session.commit()
            flash(f'Chromebook {chromebook.identifier} marked as missing.', 'warning')
    else:
        flash('Chromebook not found.', 'danger')
    return redirect(url_for('admin'))

@app.route('/mark_found/<int:chromebook_id>', methods=['POST'])
def mark_found(chromebook_id):
    chromebook = Chromebook.query.get(chromebook_id)
    if chromebook:
        chromebook.status = 'Available'
        db.session.commit()
        flash(f'Chromebook {chromebook.identifier} marked as found.', 'success')
    else:
        flash('Chromebook not found.', 'danger')
    return redirect(url_for('admin'))

def send_overdue_emails():
    with app.app_context():
        now = datetime.utcnow()
        try:
            overdue_chromebooks = Chromebook.query.filter(
                Chromebook.status == 'Loaned',
                now - Chromebook.loaned_at > timedelta(hours=24),
                Chromebook.email_sent == False
            ).all()
            logging.info(f"Fetched {len(overdue_chromebooks)} overdue Chromebooks for sending emails.")
        except Exception as e:
            logging.error(f"Error fetching overdue chromebooks: {e}")
            return

        # Group overdue Chromebooks by user
        overdue_by_user = {}
        for chromebook in overdue_chromebooks:
            user_id = chromebook.user_id
            if user_id not in overdue_by_user:
                overdue_by_user[user_id] = []
            overdue_by_user[user_id].append(chromebook)

        for user_id, user_overdue_chromebooks in overdue_by_user.items():
            user = User.query.get(user_id)
            if not user:
                logging.warning(f"No user found for user ID: {user_id}. Skipping email.")
                continue  # Skip if no user is associated with the Chromebooks

            # Ensure the recipient's email is correctly formatted
            recipient_email = user.username + ('' if '@tiffingirls.org' in user.username else '@tiffingirls.org')

            # Create email content for all of the user's overdue Chromebooks
            chromebook_identifiers = [cb.identifier for cb in user_overdue_chromebooks]
            msg = Message('Overdue Chromebook Reminder', sender=app.config['MAIL_USERNAME'], recipients=[recipient_email])
            msg.body = f'Dear {user.username},\n\nYour borrowed Chromebooks with IDs: {", ".join(chromebook_identifiers)} are now overdue. Please return them as soon as possible.\n\nThank you!'

            try:
                mail.send(msg)
                logging.info(f"Sent overdue reminder email to {recipient_email} for Chromebook IDs: {', '.join(chromebook_identifiers)}")
            except Exception as e:
                logging.error(f"Error sending email to {recipient_email}: {e}")
                continue

            # Mark the Chromebooks as having an email sent
            try:
                for cb in user_overdue_chromebooks:
                    cb.email_sent = True
                db.session.commit()
                logging.info(f"Marked Chromebook IDs: {', '.join(chromebook_identifiers)} as email_sent=True in the database.")
            except Exception as e:
                logging.error(f"Error updating Chromebook IDs in database: {e}")

if __name__ == '__main__':
    app.run