from flask import Flask, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager, get_jwt_identity
from config import DevelopmentConfig

app = Flask(__name__)
app.config.from_object(DevelopmentConfig)
app.config['JWT_IDENTITY_CLAIM'] = 'sub'
app.config['JWT_ERROR_MESSAGE_KEY'] = 'message'

db = SQLAlchemy(app)
migrate = Migrate(app, db)
jwt = JWTManager(app)

from models import User, Post, Comment
import routes

# JWT user loader callbacks
@jwt.user_identity_loader
def user_identity_lookup(user):
    # Return user ID as an integer for JWT identity
    if user and hasattr(user, 'id') and user.id is not None:
        return user.id
    return None

@jwt.user_lookup_loader
def user_lookup_callback(_jwt_header, jwt_data):
    try:
        identity = jwt_data['sub']
        # Ensure identity is treated as an integer
        if isinstance(identity, str):
            if identity.isdigit():
                identity = int(identity)
            else:
                return None
        return User.query.get(identity)
    except Exception as e:
        app.logger.error(f"Error in user_lookup_callback: {str(e)}")
        return None

@app.route('/')
def hello_world():
    return jsonify({
        'message': 'Welcome to the Blog API',
        'status': 'running',
        'endpoints': {
            'register': 'POST /register',
            'login': 'POST /login',
            'posts': 'GET /posts',
            'create_post': 'POST /posts',
            'my_posts': 'GET /my_posts'
        }
    })