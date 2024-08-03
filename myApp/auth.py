from flask import Blueprint, flash, redirect, render_template, request, url_for
from . import db
from .models import User
from flask_login import current_user, login_required, login_user, logout_user
from flask_bcrypt import generate_password_hash, check_password_hash


auth = Blueprint("auth", __name__)

@auth.route("/sign-up", methods=['GET', 'POST'])
def sign_up():
    if request.method == 'POST':
        username = request.form.get("inputUserName3")
        email = request.form.get("inputEmail3")
        password = request.form.get("inputPassword3")
        confirm_password = request.form.get("inputConfirmPassword3")

        user_email_exists = User.query.filter_by(email=email).first()
        user_username_exists = User.query.filter_by(username=username).first()

        if user_email_exists:
            flash('Email is taken.', category='error')
        elif user_username_exists:
            flash('Username is taken.', category='error')
        elif password != confirm_password:
            flash('Passwords do not match!', category='error')
        elif len(username) < 3:
            flash('Username is too short!', category='error')
        elif len(password) < 5 or len(confirm_password) < 5:
            flash('Password is too short!', category='error')
        else:
            try:
                password_hash = generate_password_hash(password)
                new_user = User(username=username, email=email, password=password_hash)
                db.session.add(new_user)
                db.session.commit()
                login_user(new_user, remember=True)
                flash('User account created successfully. You can now access your account', category='success')
                return redirect(url_for('views.home'))
            except Exception as e:
                db.session.rollback()
                flash(f'An error occurred: {str(e)}', category='error')

    return render_template("register.html", title="REGISTER")

@auth.route("/login", methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get("inputEmail3")
        password = request.form.get("inputPassword3")

        user = User.query.filter_by(email=email).first()

        if user:
            if check_password_hash(user.password, password):
                flash('Logged in successfully!', category='success')
                login_user(user, remember=True)
                return redirect(url_for('views.home'))
            else:
                flash('Incorrect password.', category='error')
        else:
            flash('Email not found. Please register first.', category='error')

    return render_template("login.html", title="LOGIN")


@auth.route("/logout")
@login_required
def logout():
    logout_user(current_user)
    flash('Logged out successfully.', category='success')
    return redirect(url_for("views.login"))