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
#
@views.route("/")
@views.route("/home")
def home():
    my_stories_data = Stories.query.all()
    return render_template("home.html", title="HOME", stories_data=my_stories_data)

#########storie and actions
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
#
@views.route("/edit-storie/<id>", methods=['GET', 'POST'])
@login_required
def edit_storie(id):
    # Fetches the current stories and populates to be changed in the form
    existing_storie = Stories.query.filter_by(id=id).first()
    if not existing_storie:
        flash('Story not found', 'danger')
        return redirect(url_for('views.home'))
    
    if existing_storie.author != current_user.id:
        flash('You are not authorized to edit this story.', 'danger')
        return redirect(url_for('views.home'))

    # Fetches form data to be updated
    if request.method == 'POST':
        title = request.form.get('title')
        category = request.form.get('category')
        content = request.form.get('content')

        # Update the story fields
        existing_storie.title = title
        existing_storie.category = category
        existing_storie.content = content

        if 'image' in request.files and request.files['image'].filename != '':
            image_file = request.files.get('image')
            filename = secure_filename(image_file.filename)
            image_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
            image_file.save(image_path)
            existing_storie.image = filename

        # Save the changes to the database
        db.session.commit()

        flash('Story updated successfully!', 'success')
        return redirect(url_for('views.home'))

    return render_template("edit_storie.html", title='edit', current_storie=existing_storie)
#
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
########storie sub actions
@views.route("/view-stories/<username>")
def view_user_stories(username):
    user = User.query.filter_by(username=username).first()
    if not user:
        flash("User not found!", category="error")
        return redirect(url_for('views.home'))
    
    user_stories = Stories.query.filter_by(author=user.id).all()
    title = f"{user.username}'s Stories"
    
    return render_template("view_user_stories.html", title=title, stories_data=user_stories)
#
@views.route("/view-storie/<id>")
def view_storie(id):
    storie = Stories.query.filter_by(id=id).first()
    if not storie:
        flash("Storie was not found!", category="error")
        return redirect(url_for('views.home'))
    title=storie.title
    return render_template("view_storie.html", title=title, storie=storie)

####storie comment sub actions
@views.route("/create-comment/<storie_id>", methods=['GET', 'POST'])
@login_required
def create_comment(storie_id):
    return(render_template("view_storie.html"))

