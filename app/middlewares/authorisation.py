import functools

from flask import flash, redirect, session, url_for


def requires_authentication(route):
    @functools.wraps(route)
    def route_wrapper(*args, **kwargs):
        if not session.get('email'):
            flash('Kindly login with your credentials')
            return redirect(url_for('login_or_register'))
        return  route(*args, **kwargs)
    return route_wrapper