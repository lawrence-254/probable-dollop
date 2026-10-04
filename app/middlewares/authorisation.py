from functools import wraps
from flask import flash, redirect, session, url_for

def requires_authentication(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("email"):
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login_or_register"))
        return view(*args, **kwargs)
    return wrapped


# import functools

# from flask import flash, redirect, session, url_for


# def requires_authentication(route):
#     """
#     Protect an admin-only route.

#     Authentication state is stored in the Flask session.
#     """

#     @functools.wraps(route)
#     def route_wrapper(*args, **kwargs):

#         if not session.get("email"):
#             flash(
#                 "Kindly log in with your credentials.",
#                 "warning",
#             )

#             return redirect(
#                 url_for("login_or_register")
#             )

#         return route(*args, **kwargs)

#     return route_wrapper
