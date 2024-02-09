from flask import Flask

app = Flask(__name__)

@app.route('/')
def hello():
    return '<h1>Hello, Flask!</h1>'

@app.route('/about')
def about():
    return 'about'
