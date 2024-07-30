from flask import Blueprint, flash, redirect, render_template, request, url_for
from . import db
from .models import User
from flask_login import login_required, login_user, logout_user
from werkzeug.security import generate_password_hash, check_password_hash

auth = Blueprint("auth", __name__)

@auth.route("/sign-up", methods=['GET', 'POST'])
def sign_up():
    if request.method=='POST':
        '''fetch user cred from user input'''
        username=request.form.get("inputUserName3")
        email=request.form.get("inputEmail3")
        password=request.form.get("inputPassword3")
        confirm_password=request.form.get("inputConfirmPassword3")

        '''fetch user cred from db'''
        user_email_exists = User.query.filter_by(email=email).first()
        user_username_exists = User.query.filter_by(username=username).first()

        '''
        check if user input is valid or taken
        then register user if the user does not user_username_exists
        '''
        if user_email_exists:
            flash('Email is taken.', category='error')
        elif user_username_exists:
            flash('Username is taken.', category='error')
        elif password != confirm_password:
            flash('Passwords do not match!', category='error')
        elif len(username) < 3:
            flash('Username is too short!', category='error')
        elif len(password) < 5 or len(confirm_password)< 5:
            flash('Password is too short!', category='error')
        else:
            hashed_password = generate_password_hash(password, method='sha256')
            new_user = User(username=username, password=hashed_password, email=email)
            db.session.add(new_user)
            db.session.commit()
            flash('User account created successfully, You can now login into your account', category='success')
            return redirect(url_for('login'))
    return render_template("register.html", title="REGISTER")



@auth.route("/login", methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        '''fetch user cred from user input'''
        email=request.form.get("inputEmail3")
        password=request.form.get("inputPassword3")

        '''fetch user cred from db'''
        user = User.query.filter_by(email=email).first()

        '''
        check if user input credentials is valid
        '''
        if user and check_password_hash(user.password, password):
            flash('Logged in successfully!', category='success')
            login_user(user)
            return redirect(url_for('main.home'))
        else:
            flash('Login unsuccessful. Please check your email and password.', category='error')


    return render_template("login.html", title="LOGIN")

@auth.route("/logout")
def logout():
    return redirect(url_for("views.home"))