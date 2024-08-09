from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename
from . import db
import os
from .models import Stories, User

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

views = Blueprint("views", __name__)

@views.route("/")
@views.route("/home")
def home():
    my_stories_data = Stories.query.all()
    return render_template("home.html", title="HOME", stories_data=my_stories_data)


@views.route("/create-storie", methods=['GET', 'POST'])
@login_required
def create_story():
    if request.method == 'POST':
        title = request.form.get('title')
        category = request.form.get('category')
        content = request.form.get('content')
        image = request.files.get('image')

        if image and allowed_file(image.filename):
            filename = secure_filename(image.filename)
            image_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
            image.save(image_path)

            new_story = Stories(
                title=title,
                image=filename,
                category=category,
                content=content,
                author=current_user.id
            )
            db.session.add(new_story)
            db.session.commit()

            flash('Your story has been created!', 'success')
            return redirect(url_for('views.home'))
        else:
            flash('New Storie created but no file uploaded', 'succes')
            new_story = Stories(
                title=title,
                image='',
                category=category,
                content=content,
                author=current_user.id
            )
            db.session.add(new_story)
            db.session.commit()

    return render_template("create_storie.html", title="NEW")

@views.route("/edit_story/<id>", methods=['GET', 'POST'])
@login_required
def edit_story(id):
    pass

@views.route("/delete-storie/<id>")
@login_required
def delete_storie(id):
    storie = Stories.query.filter_by(id=id).first()

    if not storie:
        flash("Error while trying to delete, check if the storie existx.", category="error")
    elif storie.author != current_user.id:
        flash("You do not have the permission to delete this storie!", category="error")
    else:
        db.session.delete(storie)
        db.session.commit()
        flash("Storie deleted!", category="success")
    
    
    return redirect(url_for('views.home'))

@views.route("/view-stories/<username>")
def view_user_stories(username):
    user = User.query.filter_by(username=username).first()
    if not user:
        flash("User not found!", category="error")
        return redirect(url_for('views.home'))
    
    user_stories = Stories.query.filter_by(author=user.id).all()
    title = f"{user.username}'s Stories"
    
    return render_template("view_user_stories.html", title=title, stories_data=user_stories)


@views.route("/view-storie/<id>")
def view_storie(id):
    storie = Stories.query.filter_by(id=id).first()
    if not storie:
        flash("Storie wo not found!", category="error")
        return redirect(url_for('views.home'))
    title=storie.title
    return render_template("view_storie.html", title=title, storie=storie)

