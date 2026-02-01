from flask import Flask, render_template, request, send_file, flash, redirect, url_for, session
from converter import convert_bygglosen_data
from models import db, User, LoginLog
import io
from datetime import datetime
import os
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'supersecretkey')  # Use env var or default
app.config['SESSION_COOKIE_NAME'] = 'google-login-session'

# --- Database Config ---
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///app.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

# --- OAuth Config ---
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    access_token_url='https://accounts.google.com/o/oauth2/token',
    access_token_params=None,
    authorize_url='https://accounts.google.com/o/oauth2/auth',
    authorize_params=None,
    api_base_url='https://www.googleapis.com/oauth2/v1/',
    userinfo_endpoint='https://openidconnect.googleapis.com/v1/userinfo',
    client_kwargs={'scope': 'email profile openid'},
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration'
)

# Helper function to create tables if they don't exist
with app.app_context():
    db.create_all()

@app.route('/')
def index():
    user = session.get('user')
    return render_template('index.html', user=user)

@app.route('/login')
def login():
    redirect_uri = url_for('auth', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/auth')
def auth():
    try:
        token = google.authorize_access_token()
        user_info = google.userinfo(token=token)
        
        # Spara eller uppdatera användaren i databasen
        existing_user = User.query.filter_by(google_id=user_info['id']).first()
        
        if not existing_user:
            existing_user = User(
                google_id=user_info['id'],
                email=user_info['email'],
                name=user_info.get('name'),
                picture=user_info.get('picture')
            )
            db.session.add(existing_user)
        else:
            # Uppdatera info om det ändrats (t.ex. bild eller namn)
            existing_user.name = user_info.get('name')
            existing_user.picture = user_info.get('picture')
        
        # Logga inloggningstillfället
        log_entry = LoginLog(user=existing_user)
        db.session.add(log_entry)
        db.session.commit()

        # Spara i sessionen
        session['user'] = user_info
        return redirect('/')
    except Exception as e:
        flash(f'Inloggning misslyckades: {str(e)}')
        return redirect('/')

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect('/')

@app.route('/convert', methods=['POST'])
def convert():
    if not session.get('user'):
        flash('Du måste logga in för att konvertera filer.')
        return redirect('/')

    xml_files = request.files.getlist('xml_files')
    csv_file = request.files.get('csv_file')
    
    if not xml_files or not csv_file:
        flash('Både XML och CSV måste laddas upp.')
        return redirect('/')
        
    if any(f.filename == '' for f in xml_files) or csv_file.filename == '':
        flash('Ingen fil vald.')
        return redirect('/')
        
    if xml_files and csv_file:
        try:
            xml_streams = [f.stream for f in xml_files]
            result_stream = convert_bygglosen_data(xml_streams, csv_file.stream)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"LOSEN_konverterad_{timestamp}.xml"
            return send_file(
                result_stream,
                as_attachment=True,
                download_name=filename,
                mimetype='application/xml'
            )
        except Exception as e:
            flash(f'Ett fel uppstod vid konvertering: {str(e)}')
            return redirect('/')
    
    return redirect('/')

if __name__ == '__main__':
    app.run(debug=True)
