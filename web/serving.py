import os

from flask import Blueprint, redirect, render_template, send_from_directory

from .state import IMAGE_DIR, OUTPUT_DIR, db

bp = Blueprint("serving", __name__)

@bp.route("/")
def index():
    return render_template("admin.html")

@bp.route("/images/<path:filename>")
def serve_image(filename):
    """Serve cached images from persistent volume (/data/images/) or local cache."""
    import os
    image_dir = os.environ.get("IMAGE_CACHE_DIR", "/data/images")
    if not os.path.isdir(image_dir):
        image_dir = IMAGE_DIR  # fallback to local static/images
    return send_from_directory(image_dir, filename)

@bp.route("/latest")
def serve_latest():
    """302 redirect to latest published issue H5."""
    issues = db.get_all_issues()
    published = [i for i in issues if i.get("status") == "published" and i.get("html_path")]
    if not published:
        return "No published issues yet", 404
    latest = published[-1]  # last published
    h5 = latest["html_path"].split("/")[-1]
    return redirect(f"/output/{h5}", code=302)

@bp.route("/issue/<issue_number>")
def serve_issue(issue_number):
    """Serve H5 for a specific issue number, 404 if not found."""
    issue = db.get_issue_by_number(issue_number)
    if not issue or not issue.get("html_path"):
        return f"Issue {issue_number} not found", 404
    h5 = issue["html_path"].split("/")[-1]
    return send_from_directory(OUTPUT_DIR, h5)

@bp.route("/output/<path:filename>")
def serve_output(filename):
    return send_from_directory(OUTPUT_DIR, filename)

@bp.route("/static/images/<path:filename>")
def serve_images(filename):
    return send_from_directory(IMAGE_DIR, filename)
