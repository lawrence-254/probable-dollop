from flask import Blueprint, render_template, redirect, url_for, request

auth = Blueprint("auth", __name__)

@auth.route("/sign-up", methods=['GET', 'POST'])
def sign_up():
    username=request.form.get("inputUserName3")
    email=request.form.get("inputEmail3")
    password=request.form.get("inputPassword3")
    confirm_password=request.form.get("inputConfirmPassword3")
    print(username, email, password, confirm_password)
    return render_template("register.html", title="REGISTER")

@auth.route("/login", methods=['GET', 'POST'])
def login():
    email=request.form.get("inputEmail3")
    password=request.form.get("inputPassword3")
    print(email, password)
    return render_template("login.html", title="LOGIN")

@auth.route("/logout")
def logout():
    return redirect(url_for("views.home"))