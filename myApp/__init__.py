from flask import Flask
from flask_sqlalchemy import SQLAlchemy
import os
from os import path
from flask_bcrypt import Bcrypt
from flask_login import LoginManager


db=SQLAlchemy()
DB_NAME="storie.db"

def create_app():
    '''
    A function that configures my flask app the starts the connection
    returns an instance of an app that is ready to be executed
    '''
    app = Flask(__name__)
    app.config['SECRET_KEY']='secrete'

    '''Database setup'''
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_NAME}'
    app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'uploads')
    db.init_app(app)
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    '''models'''
    from .models import User, Stories
    create_database(app, DB_NAME)
    bcrypt = Bcrypt(app)

    '''importing different routes from different models[vies,  models]'''
    from .views import views
    from .auth import auth

    '''Registering the imported access routes'''
    app.register_blueprint(views, url_prefix="/")
    app.register_blueprint(auth, url_prefix="/")

    '''login manager'''
    login_manager = LoginManager()
    login_manager.login_view ="auth.login"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(id):
        return User.query.get(int(id))


    return app


def create_database(app, db_name):
    '''
    A function that checks if there is an instance of the defined database structure in the app
    this function creates the database when there is no instance oo=f the defined database
    '''
    if not path.exists(os.path.join("myApp", db_name)):
        with app.app_context():
            db.create_all()
        print("Database created successfully")
