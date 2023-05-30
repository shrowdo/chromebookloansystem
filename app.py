from flask import Flask, render_template, request, redirect, url_for, abort, flash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime, timedelta
from urllib.parse import quote
from nameparser import HumanName
import os
import pytz
import psycopg2
import re

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')

# Fetch the DATABASE_URL from environment variable
database_url = os.getenv('DATABASE_URL')

# Fetch the ADMIN_PASSWORD from environment variable
admin_password = os.environ.get('ADMIN_PASSWORD')

# Fix for Heroku's "postgres://" prefix
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# ... rest of your code ...

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    chromebooks = db.relationship('Chromebook', backref='user', lazy=True)

class Chromebook(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    identifier = db.Column(db.String(80), unique=True, nullable=False)
    serial_number = db.Column(db.String(80), unique=True, nullable=False)  # New field
    is_loaned = db.Column(db.Boolean, default=False, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    loaned_at = db.Column(db.DateTime, nullable=True)

@app.route('/')
def home():
    chromebooks = Chromebook.query.filter_by(is_loaned=False).all()
    chromebooks.sort(key=lambda x: int(x.identifier)) # Sorting in Python

    loaned_chromebooks = Chromebook.query.filter_by(is_loaned=True).all()
    loaned_chromebooks.sort(key=lambda x: int(x.identifier)) # Sorting in Python

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
    if chromebook.is_loaned:
        flash(('Chromebook is already loaned.', 'danger'))
        return redirect(url_for('home'))

    chromebook.is_loaned = True
    chromebook.user_id = user.id
    chromebook.loaned_at = datetime.utcnow()
    db.session.commit()

    flash(f'Device {chromebook.identifier} Loaned. Thank You. Please return by 4pm', 'success')

    return redirect(url_for('home'))

def datetimefilter(value, format='%Y-%m-%d %H:%M:%S'):
    utc = pytz.timezone('UTC')
    london_tz = pytz.timezone('Europe/London')
    value = utc.localize(value)
    return value.astimezone(london_tz).strftime(format)

app.jinja_env.filters['datetimefilter'] = datetimefilter

@app.route('/return', methods=['POST'])
def return_chromebook():
    chromebook_id = request.form.get('chromebook_id')

    chromebook = Chromebook.query.get(chromebook_id)
    if chromebook and chromebook.is_loaned:
        chromebook.is_loaned = False
        chromebook.user_id = None
        chromebook.loaned_at = None
        db.session.commit()

        flash('Thank you!', 'success')
    else:
        flash(('Chromebook is not currently loaned.', 'danger'))

    return redirect(url_for('home'))

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    filter_by = request.args.get('filter', 'all')  # Get the filter status from the query parameters

    if request.method == 'POST':
        password = request.form.get('password')
        if password != admin_password:
            flash('Incorrect password. Please try again.')
            return redirect(url_for('home'))

    users = User.query.all()
    now = datetime.utcnow()

    chromebooks = Chromebook.query
    if filter_by == 'all':
        chromebooks = chromebooks.all()  # Fetch all chromebooks
    elif filter_by == 'available':
        chromebooks = chromebooks.filter_by(is_loaned=False).all()  # Filter by available chromebooks
    elif filter_by == 'loaned':
        chromebooks = chromebooks.filter_by(is_loaned=True).all()  # Filter by loaned chromebooks
    elif filter_by == 'overdue':
        chromebooks = chromebooks.filter(Chromebook.is_loaned == True, now - Chromebook.loaned_at > timedelta(hours=24)).all()  # Filter by overdue chromebooks

    # Sort by identifier in numeric order, regardless of filter
    chromebooks = sorted(chromebooks, key=lambda cb: int(cb.identifier))  
    
    # Create list of email addresses of users with overdue Chromebooks
    overdue_chromebook_emails = [chromebook.user.username + ('' if '@tiffingirls.org' in chromebook.user.username else '@tiffingirls.org') for chromebook in chromebooks if chromebook.is_loaned and (now - chromebook.loaned_at > timedelta(hours=24))]

    # Create list of names of users with overdue Chromebooks
    overdue_chromebook_usernames = [re.sub(r'^\d{2}|@tiffingirls.org$', '', chromebook.user.username) for chromebook in chromebooks if chromebook.is_loaned and (now - chromebook.loaned_at > timedelta(hours=24))]
    overdue_chromebook_names = [f'{username[0].upper()} {username[1:].capitalize()}' for username in overdue_chromebook_usernames]
    
    # Create a mailto link for reception
    reception_email = "reception@tiffingirls.org"
    reception_subject = quote("Overdue Chromebook Report")
    reception_body = quote(f"Dear Reception,\n\nThe following users have Chromebooks that are overdue for return:\n\n" + "\n".join(overdue_chromebook_names) + "\n\nPlease follow up with them.\n\nThank you.")
    reception_mailto_link = f'mailto:{reception_email}?subject={reception_subject}&body={reception_body}'

    # Create a mailto link
    subject = quote("Overdue Chromebook Reminder")
    body = quote("Dear User,\n\nOur records indicate that you have a Chromebook that is overdue for return. Please return it as soon as possible.\n\nThank you.")
    mailto_link = f'mailto:{";".join(overdue_chromebook_emails)}?subject={subject}&body={body}'
    
    return render_template('admin.html', chromebooks=chromebooks, users=users, mailto_link=mailto_link, reception_mailto_link=reception_mailto_link)

@app.route('/add_chromebook', methods=['POST'])
def add_chromebook():
    identifier = request.form.get('identifier')
    serial_number = request.form.get('serial_number')  # New field
    
    if identifier and serial_number:
        chromebook = Chromebook(identifier=identifier, serial_number=serial_number)  # New field
        db.session.add(chromebook)
        db.session.commit()
    
    return redirect(url_for('admin'))

@app.route('/edit_chromebook/<int:chromebook_id>', methods=['POST'])
def edit_chromebook(chromebook_id):
    # Lookup the Chromebook by ID
    chromebook = Chromebook.query.get(chromebook_id)
    if not chromebook:
        abort(404)
    # Update the Chromebook with the new values from the form
    chromebook.identifier = request.form.get('identifier')
    chromebook.serial_number = request.form.get('serial_number')
    # Save the changes
    db.session.commit()
    return redirect(url_for('admin'))

@app.route('/delete_chromebook/<int:chromebook_id>', methods=['POST'])
def delete_chromebook(chromebook_id):
    chromebook = Chromebook.query.get_or_404(chromebook_id)
    db.session.delete(chromebook)
    db.session.commit()
    return redirect(url_for('admin'))

if __name__ == '__main__':
    app.run(debug=True)