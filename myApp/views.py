from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename
from . import db
import os
from .models import Stories

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

views = Blueprint("views", __name__)

@views.route("/")
@views.route("/home")
@login_required
def home():
    return render_template("home.html", title="HOME")

@views.route("/create-storie", methods=['GET', 'POST'])
@login_required
def create_storie():
    if request.method == 'POST':
        title = request.form.get('title')
        category = request.form.get('category')
        content = request.form.get('content')
        if 'image' not in request.files:
            flash('No file part', 'error')
            return redirect(request.url)
        file = request.files['image']
        if file.filename == '':
            flash('No selected file', 'error')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)

            new_story = Stories(title=title, image=filename, category=category, content=content, author=current_user.id)
            db.session.add(new_story)
            db.session.commit()
            
            flash('Your story has been created!', 'success')
            return redirect(url_for('views.home'))
        else:
            flash('Invalid file type', 'error')
            return redirect(request.url)
    return render_template("create_storie.html", title="NEW")

@views.route("/view-storie")
@login_required
def view_storie():
    return render_template("view_storie.html", title="Story Title")