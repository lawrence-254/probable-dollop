#!/usr/bin/python3
"""Single-admin portfolio app: public pages + one admin who manages
projects/about content and can reset their password via email or SMS."""

import hashlib
import json
import os
import secrets
import smtplib
import uuid
from datetime import datetime, timedelta
from email.message import EmailMessage

from flask import (
    Flask,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from .middlewares.authorisation import requires_authentication

# ================================================================
# Configuration
# ================================================================

basedir = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)

DEFAULT_SECRET_KEY = "our-secret-key-change-this-in-production-123"

app.config.update(
    SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL")
    or "sqlite:///" + os.path.join(basedir, "app.db"),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SECRET_KEY=os.environ.get("SECRET_KEY", DEFAULT_SECRET_KEY),
    UPLOAD_FOLDER=os.path.join(basedir, "static", "uploads"),
    MAX_CONTENT_LENGTH=16 * 1024 * 1024,
    # Reset-flow tuning
    RESET_CODE_EXPIRY_MINUTES=int(os.environ.get("RESET_CODE_EXPIRY_MINUTES", "10")),
    RESET_REQUEST_COOLDOWN_SECONDS=int(os.environ.get("RESET_REQUEST_COOLDOWN_SECONDS", "60")),
    # Email (SMTP)
    MAIL_HOST=os.environ.get("MAIL_HOST", "smtp.gmail.com"),
    MAIL_PORT=int(os.environ.get("MAIL_PORT", "587")),
    MAIL_USERNAME=os.environ.get("MAIL_USERNAME", ""),
    MAIL_PASSWORD=os.environ.get("MAIL_PASSWORD", ""),
    MAIL_USE_TLS=os.environ.get("MAIL_USE_TLS", "true").lower() == "true",
    # Twilio (SMS)
    TWILIO_ACCOUNT_SID=os.environ.get("TWILIO_ACCOUNT_SID", ""),
    TWILIO_AUTH_TOKEN=os.environ.get("TWILIO_AUTH_TOKEN", ""),
    TWILIO_PHONE_NUMBER=os.environ.get("TWILIO_PHONE_NUMBER", ""),
    # Session/cookie hardening
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("FLASK_ENV") == "production",
)
app.config["MAIL_FROM"] = os.environ.get("MAIL_FROM", app.config["MAIL_USERNAME"])

if app.config["SECRET_KEY"] == DEFAULT_SECRET_KEY:
    app.logger.warning(
        "SECRET_KEY is using the insecure default. Set the SECRET_KEY "
        "environment variable before deploying to production."
    )

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

db = SQLAlchemy(app)

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
ALLOWED_CV_EXTENSIONS = {"pdf"}


# ================================================================
# Models
# ================================================================

class User(db.Model):
    """Single admin account. Email is the primary key."""

    email = db.Column(db.String(200), primary_key=True)
    password = db.Column(db.String(256), nullable=False)
    phone = db.Column(db.String(30), unique=True, nullable=True)

    # Password reset state
    reset_code_hash = db.Column(db.String(128), nullable=True)
    reset_code_expires_at = db.Column(db.DateTime, nullable=True)
    reset_requested_at = db.Column(db.DateTime, nullable=True)


class About(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bio = db.Column(db.Text)
    techstack = db.Column(db.Text)
    familiar = db.Column(db.Text)
    future = db.Column(db.Text)
    cv = db.Column(db.String(300))

    def get_techstack(self):
        return json.loads(self.techstack) if self.techstack else []

    def get_familiar(self):
        return json.loads(self.familiar) if self.familiar else []

    def get_future(self):
        return json.loads(self.future) if self.future else []


class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    thumb = db.Column(db.String(300))
    hero = db.Column(db.String(300))
    category = db.Column(db.Text)
    description = db.Column(db.Text)
    aims = db.Column(db.Text)
    slug = db.Column(db.String(120), unique=True, nullable=False)
    live_site = db.Column(db.String(300))
    preview_video_link = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def get_categories(self):
        return json.loads(self.category) if self.category else []

    def get_aims(self):
        return json.loads(self.aims) if self.aims else []


with app.app_context():
    db.create_all()


# ================================================================
# Template context
# ================================================================

@app.context_processor
def inject_session_email():
    """Make `email` available in every template without repeating
    `email=session.get("email")` in each route."""
    return {"email": session.get("email")}


# ================================================================
# General helpers
# ================================================================

def allowed_file(filename: str, allowed_set: set) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_set


def parse_csv_field(raw: str) -> list:
    """Turn a comma-separated form field into a clean list of strings."""
    return [item.strip() for item in raw.split(",") if item.strip()]


def generate_unique_slug(name: str) -> str:
    base_slug = name.lower().strip().replace(" ", "-")
    slug = base_slug
    counter = 1
    while Project.query.filter_by(slug=slug).first():
        slug = f"{base_slug}-{counter}"
        counter += 1
    return slug


def save_uploaded_file(file, allowed_extensions: set, folder=None):
    """Save an uploaded file if its extension is in `allowed_extensions`.

    Returns a path relative to the `static/` folder (e.g. "uploads/xyz.png"),
    or None if there is no file or it's not an allowed type.
    """
    if not file or not file.filename:
        return None

    if not allowed_file(file.filename, allowed_extensions):
        return None

    folder = folder or app.config["UPLOAD_FOLDER"]
    filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
    file.save(os.path.join(folder, filename))

    if folder == app.config["UPLOAD_FOLDER"]:
        return f"uploads/{filename}"
    return filename


# ================================================================
# Password reset helpers
# ================================================================

def normalize_phone(phone: str) -> str:
    phone = phone.strip().replace(" ", "").replace("-", "")
    if phone.startswith("00"):
        phone = "+" + phone[2:]
    return phone


def generate_reset_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_reset_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def clear_reset_data(user: User) -> None:
    user.reset_code_hash = None
    user.reset_code_expires_at = None
    user.reset_requested_at = None
    db.session.commit()


def get_active_reset_user(email: str):
    """Return the User mid-reset for `email`, or None if there is no
    valid, unexpired reset in progress (expired state is cleared)."""
    if not email:
        return None

    user = User.query.filter_by(email=email).first()
    if not user or not user.reset_code_hash:
        return None

    if not user.reset_code_expires_at or user.reset_code_expires_at < datetime.utcnow():
        clear_reset_data(user)
        return None

    return user


def send_reset_email(email: str, code: str) -> None:
    cfg = current_app.config
    if not cfg["MAIL_USERNAME"] or not cfg["MAIL_PASSWORD"]:
        raise RuntimeError("Email service is not configured.")

    message = EmailMessage()
    message["Subject"] = "Password Reset Code"
    message["From"] = cfg["MAIL_FROM"]
    message["To"] = email
    message.set_content(
        f"Password Reset\n\n"
        f"Your password reset code is:\n\n{code}\n\n"
        f"This code expires in {cfg['RESET_CODE_EXPIRY_MINUTES']} minutes.\n\n"
        f"If you did not request a password reset, you can safely ignore this email."
    )

    with smtplib.SMTP(cfg["MAIL_HOST"], cfg["MAIL_PORT"], timeout=20) as smtp:
        if cfg["MAIL_USE_TLS"]:
            smtp.starttls()
        smtp.login(cfg["MAIL_USERNAME"], cfg["MAIL_PASSWORD"])
        smtp.send_message(message)


def send_reset_sms(phone: str, code: str) -> None:
    cfg = current_app.config
    sid, token, from_phone = (
        cfg["TWILIO_ACCOUNT_SID"],
        cfg["TWILIO_AUTH_TOKEN"],
        cfg["TWILIO_PHONE_NUMBER"],
    )
    if not sid or not token or not from_phone:
        raise RuntimeError("SMS service is not configured.")

    try:
        from twilio.rest import Client
    except ImportError as exc:
        raise RuntimeError("Twilio is not installed.") from exc

    Client(sid, token).messages.create(
        body=(
            f"Your password reset code is {code}. "
            f"It expires in {cfg['RESET_CODE_EXPIRY_MINUTES']} minutes."
        ),
        from_=from_phone,
        to=phone,
    )


# ================================================================
# Public routes
# ================================================================

@app.route("/")
def home():
    projects = Project.query.order_by(Project.created_at.desc()).all()
    return render_template("home.html", projects=projects)


@app.route("/about")
def about():
    return render_template("about.html", portfolio_about=About.query.first())


@app.route("/contact")
def contact():
    return render_template("contact.html")


@app.route("/project/<string:slug>/")
def project_detail(slug):
    project = Project.query.filter_by(slug=slug).first_or_404()
    return render_template("project_view.html", project=project)


@app.errorhandler(404)
def page_not_found(error):
    return render_template("404.html"), 404


@app.route("/download-cv")
def download_cv():
    about_entry = About.query.first()
    if not about_entry or not about_entry.cv:
        abort(404)

    directory = os.path.join(current_app.root_path, "static")
    return send_from_directory(
        directory,
        about_entry.cv,
        as_attachment=True,
        download_name="Lawrence_Odhiambo_CV.pdf",
    )


# ================================================================
# Login / first-run registration
# ================================================================

@app.route("/login", methods=["GET", "POST"])
def login_or_register():
    if request.method != "POST":
        return render_template("auth/login.html")

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "").strip()

    if not email or not password:
        flash("Email and password are required.", "danger")
        return redirect(url_for("login_or_register"))

    users = User.query.limit(2).all()
    if len(users) > 1:
        # This application must contain exactly zero or one admin.
        flash("Multiple admin accounts detected. Contact support.", "danger")
        abort(401)

    if users:
        user = users[0]
        if user.email == email and check_password_hash(user.password, password):
            session.clear()
            session["email"] = user.email
            flash("Welcome back!", "success")
            return redirect(url_for("add_information"))

        flash("Incorrect credentials.", "danger")
        return render_template("auth/login.html")

    # First-ever admin sign-up.
    new_user = User(email=email, password=generate_password_hash(password))
    db.session.add(new_user)
    db.session.commit()

    session.clear()
    session["email"] = new_user.email
    flash("Admin account created successfully!", "success")
    return redirect(url_for("add_information"))


# ================================================================
# Forgot password
# ================================================================

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method != "POST":
        return render_template("auth/forgot_password.html")

    identifier = request.form.get("identifier", "").strip()
    if not identifier:
        flash("Enter your email or phone number.", "danger")
        return redirect(url_for("forgot_password"))

    user = User.query.filter_by(email=identifier.lower()).first()
    if not user:
        user = User.query.filter_by(phone=normalize_phone(identifier)).first()

    if not user:
        # Don't reveal whether the account exists.
        flash(
            "If those details match the admin account, a reset code has been sent.",
            "info",
        )
        return redirect(url_for("forgot_password"))

    now = datetime.utcnow()
    cooldown = current_app.config["RESET_REQUEST_COOLDOWN_SECONDS"]
    if user.reset_requested_at and (now - user.reset_requested_at).total_seconds() < cooldown:
        flash(
            "A reset code was recently sent. Please wait before requesting another one.",
            "warning",
        )
        return redirect(url_for("forgot_password"))

    code = generate_reset_code()
    user.reset_code_hash = hash_reset_code(code)
    user.reset_code_expires_at = now + timedelta(
        minutes=current_app.config["RESET_CODE_EXPIRY_MINUTES"]
    )
    user.reset_requested_at = now
    db.session.commit()

    try:
        if identifier.lower() == user.email.lower():
            send_reset_email(user.email, code)
            method = "email"
        else:
            if not user.phone:
                raise RuntimeError("No recovery phone number is configured.")
            send_reset_sms(user.phone, code)
            method = "phone"
    except Exception:
        current_app.logger.exception("Password reset delivery failed.")
        clear_reset_data(user)
        flash(
            "We could not send the reset code. Please check your recovery configuration.",
            "danger",
        )
        return redirect(url_for("forgot_password"))

    session["password_reset_email"] = user.email
    session.pop("password_reset_verified", None)
    flash(f"A reset code was sent to your {method}.", "success")
    return redirect(url_for("verify_reset_code"))


# ================================================================
# Verify reset code
# ================================================================

@app.route("/verify-reset-code", methods=["GET", "POST"])
def verify_reset_code():
    email = session.get("password_reset_email")
    user = get_active_reset_user(email)

    if not user:
        session.pop("password_reset_email", None)
        flash("Invalid or expired reset request. Please start again.", "danger")
        return redirect(url_for("forgot_password"))

    if request.method != "POST":
        return render_template("auth/verify_reset_code.html")

    code = request.form.get("code", "").strip()
    if len(code) != 6 or not code.isdigit():
        flash("Enter the 6-digit reset code.", "danger")
        return render_template("auth/verify_reset_code.html")

    if not secrets.compare_digest(hash_reset_code(code), user.reset_code_hash):
        flash("Invalid reset code.", "danger")
        return render_template("auth/verify_reset_code.html")

    session["password_reset_verified"] = True
    flash("Code verified. Choose your new password.", "success")
    return redirect(url_for("reset_password"))


# ================================================================
# Reset password
# ================================================================

@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    email = session.get("password_reset_email")

    if not session.get("password_reset_verified"):
        flash("Verify your reset code first.", "warning")
        return redirect(url_for("forgot_password"))

    user = get_active_reset_user(email)
    if not user:
        session.pop("password_reset_email", None)
        session.pop("password_reset_verified", None)
        flash("Your reset session has expired. Please start again.", "danger")
        return redirect(url_for("forgot_password"))

    if request.method != "POST":
        return render_template("auth/reset_password.html")

    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not password or not confirm_password:
        flash("Both password fields are required.", "danger")
    elif password != confirm_password:
        flash("Passwords do not match.", "danger")
    elif len(password) < 8:
        flash("Password must be at least 8 characters long.", "danger")
    else:
        user.password = generate_password_hash(password)
        clear_reset_data(user)  # also commits
        session.clear()
        flash("Your password has been reset successfully. You can now log in.", "success")
        return redirect(url_for("login_or_register"))

    return render_template("auth/reset_password.html")


# ================================================================
# Admin information
# ================================================================

def _handle_add_project():
    title = request.form.get("title", "").strip()
    if not title:
        flash("Project title is required.", "danger")
        return redirect(url_for("add_information"))

    thumb_path = save_uploaded_file(
        request.files.get("thumbnail"), ALLOWED_IMAGE_EXTENSIONS
    )
    hero_path = save_uploaded_file(
        request.files.get("hero"), ALLOWED_IMAGE_EXTENSIONS
    )

    project = Project(
        name=title,
        thumb=thumb_path,
        hero=hero_path,
        category=json.dumps(parse_csv_field(request.form.get("tech", ""))),
        description=request.form.get("description", "").strip(),
        aims=json.dumps(parse_csv_field(request.form.get("aim", ""))),
        slug=generate_unique_slug(title),
        live_site=request.form.get("live_link", "").strip(),
        preview_video_link=request.form.get("video_link", "").strip(),
    )
    db.session.add(project)
    db.session.commit()

    flash("Project added successfully!", "success")
    return redirect(url_for("add_information"))


def _handle_edit_about():
    about_entry = About.query.first() or About()

    about_entry.bio = request.form.get("bio", "").strip()
    about_entry.techstack = json.dumps(
        parse_csv_field(request.form.get("techstack_used_extensively", ""))
    )
    about_entry.familiar = json.dumps(
        parse_csv_field(request.form.get("familiar_techstack", ""))
    )
    about_entry.future = json.dumps(
        parse_csv_field(request.form.get("interested_in_techstack", ""))
    )

    cv_file = request.files.get("cv")
    if cv_file and cv_file.filename:
        cv_path = save_uploaded_file(cv_file, ALLOWED_CV_EXTENSIONS)
        if cv_path:
            if about_entry.cv:
                old_path = os.path.join(app.root_path, "static", about_entry.cv)
                if os.path.exists(old_path):
                    try:
                        os.remove(old_path)
                    except OSError as exc:
                        app.logger.warning("Failed to delete old CV: %s", exc)
            about_entry.cv = cv_path

    db.session.add(about_entry)
    db.session.commit()

    flash("Profile updated successfully!", "success")
    return redirect(url_for("add_information"))


@app.route("/information", methods=["GET", "POST"])
@requires_authentication
def add_information():
    if request.method == "POST":
        if "logout_button" in request.form:
            session.clear()
            flash("You have been logged out.", "info")
            return redirect(url_for("login_or_register"))

        if "add_project_button" in request.form:
            return _handle_add_project()

        if "edit_about_button" in request.form:
            return _handle_edit_about()

    projects = Project.query.order_by(Project.created_at.desc()).all()
    return render_template(
        "auth/information.html",
        projects=projects,
        about=About.query.first(),
    )


# ================================================================
# Run
# ================================================================

if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "true").lower() == "true"
    app.run(debug=debug_mode)
