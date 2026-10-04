#!/usr/bin/env python3
"""
Single-admin portfolio application.

Features:
- Public portfolio pages
- One administrator account
- Admin login/logout
- Project management (create / edit / delete)
- About/profile management
- Admin account profile (phone + password)
- CV upload/download
- Password reset through email
- Password reset through SMS when Twilio is configured
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import smtplib
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from functools import wraps
from pathlib import Path

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


# ================================================================
# Environment
# ================================================================

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


# ================================================================
# Application paths
# ================================================================

BASEDIR = Path(__file__).resolve().parent
STATIC_DIR = BASEDIR / "static"
UPLOAD_FOLDER = STATIC_DIR / "uploads"
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)


# ================================================================
# Application
# ================================================================

app = Flask(__name__)


# ================================================================
# Configuration helpers
# ================================================================

def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(
            f"Environment variable {name} must be an integer."
        ) from exc


IS_PRODUCTION = os.getenv("FLASK_ENV", "").strip().lower() == "production"


# ================================================================
# Secret key
# ================================================================

SECRET_KEY = os.getenv("SECRET_KEY", "").strip()

if not SECRET_KEY:
    if IS_PRODUCTION:
        raise RuntimeError(
            "SECRET_KEY is required in production. "
            "Generate a strong random value and place it in .env."
        )
    SECRET_KEY = secrets.token_hex(32)
    print(
        "WARNING: SECRET_KEY was not provided. "
        "A temporary development key was generated."
    )


# ================================================================
# Flask configuration
# ================================================================

app.config.update(
    SECRET_KEY=SECRET_KEY,
    SQLALCHEMY_DATABASE_URI=(
        os.getenv("DATABASE_URL", "").strip()
        or f"sqlite:///{BASEDIR / 'app.db'}"
    ),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    UPLOAD_FOLDER=str(UPLOAD_FOLDER),
    MAX_CONTENT_LENGTH=16 * 1024 * 1024,
    # Password reset
    RESET_CODE_EXPIRY_MINUTES=env_int("RESET_CODE_EXPIRY_MINUTES", 10),
    RESET_REQUEST_COOLDOWN_SECONDS=env_int("RESET_REQUEST_COOLDOWN_SECONDS", 60),
    # SMTP
    MAIL_HOST=os.getenv("MAIL_HOST", "smtp.gmail.com").strip(),
    MAIL_PORT=env_int("MAIL_PORT", 587),
    MAIL_USE_TLS=env_bool("MAIL_USE_TLS", True),
    MAIL_USERNAME=os.getenv("MAIL_USERNAME", "").strip(),
    MAIL_PASSWORD=os.getenv("MAIL_PASSWORD", "").strip(),
    MAIL_FROM=os.getenv("MAIL_FROM", "").strip(),
    # Twilio
    TWILIO_ACCOUNT_SID=os.getenv("TWILIO_ACCOUNT_SID", "").strip(),
    TWILIO_AUTH_TOKEN=os.getenv("TWILIO_AUTH_TOKEN", "").strip(),
    TWILIO_PHONE_NUMBER=os.getenv("TWILIO_PHONE_NUMBER", "").strip(),
    # Session security
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=IS_PRODUCTION,
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
)

if not app.config["MAIL_FROM"]:
    app.config["MAIL_FROM"] = app.config["MAIL_USERNAME"]


# ================================================================
# Database
# ================================================================

db = SQLAlchemy(app)


# ================================================================
# Constants
# ================================================================

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
ALLOWED_CV_EXTENSIONS = {"pdf"}


# ================================================================
# Date/time helpers
# ================================================================

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def is_expired(value: datetime | None) -> bool:
    value = ensure_utc(value)
    if value is None:
        return True
    return value <= utcnow()


# ================================================================
# Auth decorator
# ================================================================

def requires_authentication(view):
    """Require a logged-in admin session."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        email = session.get("email")
        if not email:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login_or_register"))

        user = User.query.filter_by(email=normalize_email(email)).first()
        if not user:
            session.clear()
            flash("Your session is no longer valid. Please log in again.", "warning")
            return redirect(url_for("login_or_register"))

        return view(*args, **kwargs)

    return wrapped


# ================================================================
# Models
# ================================================================

class User(db.Model):
    """Single administrator account."""

    __tablename__ = "user"

    email = db.Column(db.String(200), primary_key=True)
    password = db.Column(db.String(256), nullable=False)
    phone = db.Column(db.String(30), unique=True, nullable=True)

    reset_code_hash = db.Column(db.String(128), nullable=True)
    reset_code_expires_at = db.Column(db.DateTime, nullable=True)
    reset_requested_at = db.Column(db.DateTime, nullable=True)


class About(db.Model):
    __tablename__ = "about"

    id = db.Column(db.Integer, primary_key=True)
    bio = db.Column(db.Text)
    techstack = db.Column(db.Text)
    familiar = db.Column(db.Text)
    future = db.Column(db.Text)
    cv = db.Column(db.String(300))

    @staticmethod
    def _safe_json_list(raw: str | None) -> list:
        if not raw:
            return []
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, TypeError):
            pass
        return []

    def get_techstack(self):
        return self._safe_json_list(self.techstack)

    def get_familiar(self):
        return self._safe_json_list(self.familiar)

    def get_future(self):
        return self._safe_json_list(self.future)


class Project(db.Model):
    __tablename__ = "project"

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
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.utcnow(),
        nullable=False,
    )

    @staticmethod
    def _safe_json_list(raw: str | None) -> list:
        if not raw:
            return []
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, TypeError):
            pass
        return []

    def get_categories(self):
        return self._safe_json_list(self.category)

    def get_aims(self):
        return self._safe_json_list(self.aims)


# ================================================================
# Database initialization
# ================================================================

with app.app_context():
    db.create_all()


# ================================================================
# Template context
# ================================================================

@app.context_processor
def inject_session_email():
    return {"email": session.get("email")}


# ================================================================
# General helpers
# ================================================================

def allowed_file(filename: str, allowed_extensions: set[str]) -> bool:
    if not filename or "." not in filename:
        return False
    extension = filename.rsplit(".", 1)[1].lower()
    return extension in allowed_extensions


def parse_csv_field(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[-\s]+", "-", slug)
    slug = slug.strip("-")
    return slug or "project"


def generate_unique_slug(name: str, project_id: int | None = None) -> str:
    base_slug = slugify(name)
    slug = base_slug
    counter = 1

    while True:
        query = Project.query.filter_by(slug=slug)
        if project_id is not None:
            query = query.filter(Project.id != project_id)
        if not query.first():
            return slug
        slug = f"{base_slug}-{counter}"
        counter += 1


def save_uploaded_file(file, allowed_extensions: set[str], folder: str | None = None):
    if not file or not file.filename:
        return None

    original_filename = secure_filename(file.filename)
    if not original_filename:
        return None
    if not allowed_file(original_filename, allowed_extensions):
        return None

    folder_path = Path(folder or current_app.config["UPLOAD_FOLDER"])
    folder_path.mkdir(parents=True, exist_ok=True)

    filename = f"{uuid.uuid4().hex}_{original_filename}"
    destination = folder_path / filename
    file.save(str(destination))

    if folder_path.resolve() == Path(current_app.config["UPLOAD_FOLDER"]).resolve():
        return f"uploads/{filename}"
    return filename


def delete_static_file(relative_path: str | None) -> None:
    if not relative_path:
        return

    relative_path = relative_path.replace("\\", "/").strip()
    if (
        not relative_path
        or relative_path.startswith("/")
        or ".." in relative_path.split("/")
    ):
        return

    static_root = (Path(current_app.root_path) / "static").resolve()
    target = (static_root / relative_path).resolve()

    try:
        target.relative_to(static_root)
    except ValueError:
        current_app.logger.warning(
            "Refused to delete file outside static directory: %s",
            relative_path,
        )
        return

    if target.is_file():
        try:
            target.unlink()
        except OSError as exc:
            current_app.logger.warning("Could not delete file %s: %s", target, exc)


# ================================================================
# Validation helpers
# ================================================================

def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def normalize_phone(phone: str) -> str:
    phone = (phone or "").strip()
    phone = re.sub(r"[\s().-]", "", phone)
    if phone.startswith("00"):
        phone = "+" + phone[2:]
    return phone


def is_valid_email(email: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email))


def is_valid_password(password: str) -> bool:
    return bool(password) and len(password) >= 8


def is_valid_phone(phone: str) -> bool:
    """Accept E.164-ish numbers: optional +, 8–15 digits."""
    if not phone:
        return True
    return bool(re.fullmatch(r"\+?[1-9]\d{7,14}", phone))


# ================================================================
# Password reset helpers
# ================================================================

def generate_reset_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_reset_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def clear_reset_data(user: User, commit: bool = True) -> None:
    user.reset_code_hash = None
    user.reset_code_expires_at = None
    user.reset_requested_at = None
    if commit:
        db.session.commit()


def get_active_reset_user(email: str | None):
    if not email:
        return None

    email = normalize_email(email)
    user = User.query.filter_by(email=email).first()
    if not user or not user.reset_code_hash:
        return None

    if is_expired(user.reset_code_expires_at):
        clear_reset_data(user)
        return None

    return user


def count_admins() -> int:
    return User.query.count()


# ================================================================
# Email
# ================================================================

def send_reset_email(email: str, code: str) -> None:
    cfg = current_app.config
    username = cfg["MAIL_USERNAME"]
    password = cfg["MAIL_PASSWORD"]
    mail_from = cfg["MAIL_FROM"]

    if not username:
        raise RuntimeError("MAIL_USERNAME is not configured.")
    if not password:
        raise RuntimeError("MAIL_PASSWORD is not configured.")
    if not mail_from:
        raise RuntimeError("MAIL_FROM is not configured.")

    message = EmailMessage()
    message["Subject"] = "Your Password Reset Code"
    message["From"] = mail_from
    message["To"] = email
    message.set_content(
        "Password Reset\n\n"
        f"Your password reset code is:\n\n{code}\n\n"
        f"This code expires in {cfg['RESET_CODE_EXPIRY_MINUTES']} minutes.\n\n"
        "If you did not request a password reset, you can safely ignore this email."
    )

    with smtplib.SMTP(cfg["MAIL_HOST"], cfg["MAIL_PORT"], timeout=20) as smtp:
        smtp.ehlo()
        if cfg["MAIL_USE_TLS"]:
            smtp.starttls()
            smtp.ehlo()
        smtp.login(username, password)
        smtp.send_message(message)


# ================================================================
# SMS / Twilio
# ================================================================

def send_reset_sms(phone: str, code: str) -> None:
    cfg = current_app.config
    sid = cfg["TWILIO_ACCOUNT_SID"]
    token = cfg["TWILIO_AUTH_TOKEN"]
    from_phone = cfg["TWILIO_PHONE_NUMBER"]

    if not sid:
        raise RuntimeError("TWILIO_ACCOUNT_SID is not configured.")
    if not token:
        raise RuntimeError("TWILIO_AUTH_TOKEN is not configured.")
    if not from_phone:
        raise RuntimeError("TWILIO_PHONE_NUMBER is not configured.")

    try:
        from twilio.rest import Client
    except ImportError as exc:
        raise RuntimeError(
            "Twilio is not installed. Install it with: pip install twilio"
        ) from exc

    client = Client(sid, token)
    client.messages.create(
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
    portfolio_about = About.query.first()
    return render_template("about.html", portfolio_about=portfolio_about)


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

    cv_rel = about_entry.cv.replace("\\", "/").strip()
    if not cv_rel or cv_rel.startswith("/") or ".." in cv_rel.split("/"):
        abort(404)

    static_directory = Path(current_app.root_path) / "static"
    full_path = (static_directory / cv_rel).resolve()

    try:
        full_path.relative_to(static_directory.resolve())
    except ValueError:
        abort(404)

    if not full_path.is_file():
        abort(404)

    return send_from_directory(
        str(static_directory),
        cv_rel,
        as_attachment=True,
        download_name="Lawrence_Odhiambo_CV.pdf",
    )


# ================================================================
# Login / first-run registration
# ================================================================

@app.route("/login", methods=["GET", "POST"])
def login_or_register():
    if request.method == "GET":
        return render_template("auth/login.html")

    email = normalize_email(request.form.get("email", ""))
    password = request.form.get("password", "")

    if not email or not password:
        flash("Email and password are required.", "danger")
        return redirect(url_for("login_or_register"))

    if not is_valid_email(email):
        flash("Please enter a valid email address.", "danger")
        return redirect(url_for("login_or_register"))

    admin_count = count_admins()

    if admin_count > 1:
        current_app.logger.error("Multiple admin accounts detected.")
        flash(
            "Multiple admin accounts were detected. Please contact support.",
            "danger",
        )
        return render_template("auth/login.html"), 409

    # Existing admin
    if admin_count == 1:
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            session.clear()
            session["email"] = user.email
            session.permanent = True
            flash("Welcome back!", "success")
            return redirect(url_for("add_information"))

        flash("Incorrect credentials.", "danger")
        return render_template("auth/login.html")

    # First-run admin creation
    if not is_valid_password(password):
        flash("Password must be at least 8 characters long.", "danger")
        return render_template("auth/login.html")

    new_user = User(
        email=email,
        password=generate_password_hash(password),
    )

    try:
        db.session.add(new_user)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to create administrator account.")
        flash("Unable to create the admin account.", "danger")
        return render_template("auth/login.html")

    session.clear()
    session["email"] = new_user.email
    session.permanent = True
    flash("Admin account created successfully!", "success")
    return redirect(url_for("add_information"))


# ================================================================
# Logout
# ================================================================

@app.route("/logout", methods=["POST"])
@requires_authentication
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login_or_register"))


# ================================================================
# Forgot password
# ================================================================

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "GET":
        return render_template("auth/forgot_password.html")

    identifier = request.form.get("identifier", "").strip()
    if not identifier:
        flash("Enter your email or phone number.", "danger")
        return redirect(url_for("forgot_password"))

    email_identifier = normalize_email(identifier)
    phone_identifier = normalize_phone(identifier)

    user = User.query.filter_by(email=email_identifier).first()
    delivery_method = None

    if user:
        delivery_method = "email"
    else:
        user = User.query.filter_by(phone=phone_identifier).first()
        if user:
            delivery_method = "phone"

    generic_message = (
        "If those details match the admin account, a reset code has been sent."
    )

    if not user:
        flash(generic_message, "info")
        return redirect(url_for("forgot_password"))

    now = utcnow()
    if user.reset_requested_at:
        requested_at = ensure_utc(user.reset_requested_at)
        if requested_at:
            elapsed = (now - requested_at).total_seconds()
            cooldown = current_app.config["RESET_REQUEST_COOLDOWN_SECONDS"]
            if elapsed < cooldown:
                remaining = max(1, int(cooldown - elapsed))
                flash(
                    "A reset code was recently sent. "
                    f"Please wait {remaining} seconds before requesting another one.",
                    "warning",
                )
                return redirect(url_for("forgot_password"))

    code = generate_reset_code()
    user.reset_code_hash = hash_reset_code(code)
    user.reset_code_expires_at = now + timedelta(
        minutes=current_app.config["RESET_CODE_EXPIRY_MINUTES"]
    )
    user.reset_requested_at = now

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to create password reset request.")
        flash("Unable to start the password reset. Please try again.", "danger")
        return redirect(url_for("forgot_password"))

    try:
        if delivery_method == "email":
            send_reset_email(user.email, code)
        elif delivery_method == "phone":
            if not user.phone:
                raise RuntimeError("No recovery phone number is configured.")
            send_reset_sms(user.phone, code)
        else:
            raise RuntimeError("No password reset delivery method available.")
    except Exception:
        current_app.logger.exception("Password reset delivery failed.")
        clear_reset_data(user, commit=True)
        flash(
            "We could not send the reset code. "
            "Please check your recovery configuration.",
            "danger",
        )
        return redirect(url_for("forgot_password"))

    session["password_reset_email"] = user.email
    session.pop("password_reset_verified", None)
    flash(f"A reset code was sent to your {delivery_method}.", "success")
    return redirect(url_for("verify_reset_code"))


# ================================================================
# Verify password reset code
# ================================================================

@app.route("/verify-reset-code", methods=["GET", "POST"])
def verify_reset_code():
    email = session.get("password_reset_email")
    user = get_active_reset_user(email)

    if not user:
        session.pop("password_reset_email", None)
        session.pop("password_reset_verified", None)
        flash("Invalid or expired reset request. Please start again.", "danger")
        return redirect(url_for("forgot_password"))

    if request.method == "GET":
        return render_template("auth/verify_reset_code.html")

    code = request.form.get("code", "").strip()
    if len(code) != 6 or not code.isdigit():
        flash("Enter the 6-digit reset code.", "danger")
        return render_template("auth/verify_reset_code.html")

    stored_hash = user.reset_code_hash
    if not stored_hash:
        flash("Invalid reset code.", "danger")
        return render_template("auth/verify_reset_code.html")

    if not secrets.compare_digest(hash_reset_code(code), stored_hash):
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

    if request.method == "GET":
        return render_template("auth/reset_password.html")

    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not password or not confirm_password:
        flash("Both password fields are required.", "danger")
        return render_template("auth/reset_password.html")

    if password != confirm_password:
        flash("Passwords do not match.", "danger")
        return render_template("auth/reset_password.html")

    if not is_valid_password(password):
        flash("Password must be at least 8 characters long.", "danger")
        return render_template("auth/reset_password.html")

    user.password = generate_password_hash(password)
    user.reset_code_hash = None
    user.reset_code_expires_at = None
    user.reset_requested_at = None

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to reset administrator password.")
        flash("We could not reset your password. Please try again.", "danger")
        return render_template("auth/reset_password.html")

    session.clear()
    flash(
        "Your password has been reset successfully. You can now log in.",
        "success",
    )
    return redirect(url_for("login_or_register"))


# ================================================================
# Admin project handlers
# ================================================================

def _handle_add_project():
    title = request.form.get("title", "").strip()
    if not title:
        flash("Project title is required.", "danger")
        return redirect(url_for("add_information"))

    thumbnail = request.files.get("thumbnail")
    thumb_path = None
    if thumbnail and thumbnail.filename:
        thumb_path = save_uploaded_file(thumbnail, ALLOWED_IMAGE_EXTENSIONS)
        if not thumb_path:
            flash("Invalid thumbnail file type.", "danger")
            return redirect(url_for("add_information"))

    hero = request.files.get("hero")
    hero_path = None
    if hero and hero.filename:
        hero_path = save_uploaded_file(hero, ALLOWED_IMAGE_EXTENSIONS)
        if not hero_path:
            if thumb_path:
                delete_static_file(thumb_path)
            flash("Invalid hero image file type.", "danger")
            return redirect(url_for("add_information"))

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

    try:
        db.session.add(project)
        db.session.commit()
    except Exception:
        db.session.rollback()
        if thumb_path:
            delete_static_file(thumb_path)
        if hero_path:
            delete_static_file(hero_path)
        current_app.logger.exception("Failed to create project.")
        flash("Unable to add the project.", "danger")
        return redirect(url_for("add_information"))

    flash("Project added successfully!", "success")
    return redirect(url_for("add_information"))


def _handle_edit_about():
    about_entry = About.query.first()
    if not about_entry:
        about_entry = About()

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
    new_cv_path = None
    if cv_file and cv_file.filename:
        new_cv_path = save_uploaded_file(cv_file, ALLOWED_CV_EXTENSIONS)
        if not new_cv_path:
            flash("Only PDF files are allowed for the CV.", "danger")
            return redirect(url_for("add_information"))

    old_cv_path = about_entry.cv
    if new_cv_path:
        about_entry.cv = new_cv_path

    try:
        db.session.add(about_entry)
        db.session.commit()
    except Exception:
        db.session.rollback()
        if new_cv_path:
            delete_static_file(new_cv_path)
        current_app.logger.exception("Failed to update About information.")
        flash("Unable to update your profile.", "danger")
        return redirect(url_for("add_information"))

    if new_cv_path and old_cv_path:
        delete_static_file(old_cv_path)

    flash("Profile updated successfully!", "success")
    return redirect(url_for("add_information"))


# ================================================================
# Admin information (dashboard)
# ================================================================

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
    admin = User.query.filter_by(
        email=normalize_email(session.get("email", ""))
    ).first()

    return render_template(
        "auth/information.html",
        projects=projects,
        about=About.query.first(),
        admin=admin,
    )


# ================================================================
# Admin profile management
# ================================================================

@app.route("/profile", methods=["GET", "POST"])
@requires_authentication
def admin_profile():
    """
    Manage admin recovery phone and password.
    Email is shown read-only (primary key / login identity).
    """
    email = normalize_email(session.get("email", ""))
    user = User.query.filter_by(email=email).first()

    if not user:
        session.clear()
        flash("Your session is no longer valid. Please log in again.", "warning")
        return redirect(url_for("login_or_register"))

    if request.method == "POST":
        action = request.form.get("action", "").strip()

        # Update recovery phone
        if action == "update_phone":
            raw_phone = request.form.get("phone", "").strip()
            phone = normalize_phone(raw_phone) if raw_phone else None

            if phone and not is_valid_phone(phone):
                flash(
                    "Enter a valid international phone number "
                    "(e.g. +254712345678).",
                    "danger",
                )
                return redirect(url_for("admin_profile"))

            if phone:
                other = (
                    User.query
                    .filter(User.phone == phone, User.email != user.email)
                    .first()
                )
                if other:
                    flash("That phone number is already in use.", "danger")
                    return redirect(url_for("admin_profile"))

            user.phone = phone or None

            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                current_app.logger.exception("Failed to update recovery phone.")
                flash("Unable to update phone number.", "danger")
                return redirect(url_for("admin_profile"))

            flash("Recovery phone updated.", "success")
            return redirect(url_for("admin_profile"))

        # Change password
        if action == "change_password":
            current_password = request.form.get("current_password", "")
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")

            if not current_password or not new_password or not confirm_password:
                flash("All password fields are required.", "danger")
                return redirect(url_for("admin_profile"))

            if not check_password_hash(user.password, current_password):
                flash("Current password is incorrect.", "danger")
                return redirect(url_for("admin_profile"))

            if new_password != confirm_password:
                flash("New passwords do not match.", "danger")
                return redirect(url_for("admin_profile"))

            if not is_valid_password(new_password):
                flash("New password must be at least 8 characters long.", "danger")
                return redirect(url_for("admin_profile"))

            if check_password_hash(user.password, new_password):
                flash(
                    "New password must be different from your current password.",
                    "warning",
                )
                return redirect(url_for("admin_profile"))

            user.password = generate_password_hash(new_password)
            user.reset_code_hash = None
            user.reset_code_expires_at = None
            user.reset_requested_at = None

            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                current_app.logger.exception("Failed to change admin password.")
                flash("Unable to change password. Please try again.", "danger")
                return redirect(url_for("admin_profile"))

            flash("Password changed successfully.", "success")
            return redirect(url_for("admin_profile"))

        flash("Unknown profile action.", "danger")
        return redirect(url_for("admin_profile"))

    return render_template("auth/profile.html", admin=user)


# ================================================================
# Edit project
# ================================================================

@app.route("/project/<int:project_id>/edit", methods=["GET", "POST"])
@requires_authentication
def edit_project(project_id: int):
    project = Project.query.get_or_404(project_id)

    if request.method == "GET":
        return render_template(
            "auth/edit_project.html",
            project=project,
            categories_csv=", ".join(project.get_categories()),
            aims_csv=", ".join(project.get_aims()),
        )

    title = request.form.get("title", "").strip()
    if not title:
        flash("Project title is required.", "danger")
        return redirect(url_for("edit_project", project_id=project.id))

    new_thumb = None
    thumbnail = request.files.get("thumbnail")
    if thumbnail and thumbnail.filename:
        new_thumb = save_uploaded_file(thumbnail, ALLOWED_IMAGE_EXTENSIONS)
        if not new_thumb:
            flash("Invalid thumbnail file type.", "danger")
            return redirect(url_for("edit_project", project_id=project.id))

    new_hero = None
    hero = request.files.get("hero")
    if hero and hero.filename:
        new_hero = save_uploaded_file(hero, ALLOWED_IMAGE_EXTENSIONS)
        if not new_hero:
            if new_thumb:
                delete_static_file(new_thumb)
            flash("Invalid hero image file type.", "danger")
            return redirect(url_for("edit_project", project_id=project.id))

    old_thumb = project.thumb
    old_hero = project.hero

    project.name = title
    project.slug = generate_unique_slug(title, project_id=project.id)
    project.category = json.dumps(parse_csv_field(request.form.get("tech", "")))
    project.description = request.form.get("description", "").strip()
    project.aims = json.dumps(parse_csv_field(request.form.get("aim", "")))
    project.live_site = request.form.get("live_link", "").strip()
    project.preview_video_link = request.form.get("video_link", "").strip()

    if new_thumb:
        project.thumb = new_thumb
    if new_hero:
        project.hero = new_hero

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        if new_thumb:
            delete_static_file(new_thumb)
        if new_hero:
            delete_static_file(new_hero)
        current_app.logger.exception("Failed to update project.")
        flash("Unable to update the project.", "danger")
        return redirect(url_for("edit_project", project_id=project.id))

    if new_thumb and old_thumb:
        delete_static_file(old_thumb)
    if new_hero and old_hero:
        delete_static_file(old_hero)

    flash("Project updated successfully!", "success")
    return redirect(url_for("add_information"))


# ================================================================
# Delete project
# ================================================================

@app.route("/project/<int:project_id>/delete", methods=["POST"])
@requires_authentication
def delete_project(project_id: int):
    project = Project.query.get_or_404(project_id)
    thumb = project.thumb
    hero = project.hero

    try:
        db.session.delete(project)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to delete project.")
        flash("Unable to delete the project.", "danger")
        return redirect(url_for("add_information"))

    delete_static_file(thumb)
    delete_static_file(hero)
    flash("Project deleted.", "success")
    return redirect(url_for("add_information"))


# ================================================================
# Development entry point
# ================================================================

if __name__ == "__main__":
    debug_mode = env_bool("FLASK_DEBUG", False)
    app.run(debug=debug_mode)
