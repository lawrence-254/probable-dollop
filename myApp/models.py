from . import db
from flask_login import UserMixin
from sqlalchemy.sql import func

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(240), unique=True)
    username = db.Column(db.String(240), unique=True)
    password = db.Column(db.String(240))
    date_created = db.Column(db.DateTime(timezone=True), default=func.now())
    stories = db.relationship('Stories', backref='user', passive_deletes=True)
    comments = db.relationship('Comments', backref='user', passive_deletes=True)

class Stories(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(240))
    image = db.Column(db.String(240))
    category = db.Column(db.String(240))
    content = db.Column(db.Text)
    date_created = db.Column(db.DateTime(timezone=True), default=func.now())
    author = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    Comments = db.relationship('Comments', backref='stories', passive_deletes=True)

class Comments(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    image = db.Column(db.String(240))
    content = db.Column(db.Text)
    date_created = db.Column(db.DateTime(timezone=True), default=func.now())
    storie = db.Column(db.Integer, db.ForeignKey('stories.id', ondelete='CASCADE'), nullable=False)
    author = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)

