from flask import Blueprint, redirect, render_template, request, session

from .state import ADMIN_PASSWORD

bp = Blueprint("auth", __name__)


def require_login():
    if not ADMIN_PASSWORD:
        return None
    public_paths = ("/login", "/output/", "/static/", "/images/", "/api/issue-feedback/", "/api/dj-feedback")
    if request.path.startswith(public_paths):
        return None
    if session.get("authed"):
        return None
    return redirect("/login")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["authed"] = True
            return redirect("/")
        return render_template("login.html", error=True)
    return render_template("login.html", error=False)


def add_cache_headers(response):
    """禁止浏览器缓存 HTML 页面,确保每次加载最新 JS"""
    if response.content_type and 'text/html' in response.content_type:
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response
