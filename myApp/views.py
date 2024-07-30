from flask import Blueprint,  render_template
from flask_login import current_user, login_required, login_user, logout_user

views = Blueprint("views", __name__)

@views.route("/")
@views.route("/home")
def home():
    return render_template("home.html", name="mozzart", title="HOME")

@views.route("/create-storie")
def create_storie():
    return render_template("create_storie.html", name="mozzart", title="NEW")

@views.route("/view-storie")
def view_storie():
    return render_template("view_storie.html", name="mozzart", title="storie-title")