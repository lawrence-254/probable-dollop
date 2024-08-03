from flask import Blueprint, render_template
from flask_login import current_user, login_required

views = Blueprint("views", __name__)

@views.route("/")
@views.route("/home")
@login_required
def home():
    return render_template("home.html", title="HOME")

@views.route("/create-storie")
@login_required
def create_story():
    return render_template("create_storie.html", title="NEW")

@views.route("/view-storie")
@login_required
def view_story():
    return render_template("view_storie.html", title="Story Title")