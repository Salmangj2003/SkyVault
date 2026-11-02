"""
SkyVault / PG Cloud Drive - Flask application
Required packages:
    pip install Flask mysql-connector-python Werkzeug mammoth pdfkit

System tools:
    ffmpeg (for video HLS conversion and thumbnails)
    pandoc (optional, for editing DOCX files)

Set environment variables before running:
    DB_HOST, DB_USER, DB_PASSWORD, DB_NAME, SECRET_KEY, ADMIN_EMAIL
"""

import datetime
import os
import secrets
import shutil
import subprocess
import threading
import uuid
from pathlib import Path

import mammoth
import mysql.connector
import pdfkit
from flask import (
    Flask, Response, abort, flash, jsonify, redirect, render_template,
    request, send_file, send_from_directory, session, url_for
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"

load_dotenv(dotenv_path=ENV_FILE, override=True)


# ---------------------------------------------------------------------
# APP CONFIGURATION
# ---------------------------------------------------------------------

app = Flask(__name__)

app.secret_key = os.getenv("SECRET_KEY")

if not app.secret_key:
    raise RuntimeError("SECRET_KEY environment variable is missing")
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER = BASE_DIR / "uploads"
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)

TOTAL_STORAGE = 18 * 1024  # 18 GB, stored as MB
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "salmangj112@gmail.com").lower()


# ---------------------------------------------------------------------
# DATABASE
# ---------------------------------------------------------------------

def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME")
    )


# ---------------------------------------------------------------------
# VIDEO PROCESSING
# ---------------------------------------------------------------------

VIDEO_EXTENSIONS = {"mp4", "mkv", "mov", "avi", "webm", "m4v", "flv", "wmv"}


def convert_to_hls(input_path, output_folder):
    """Convert a video to HLS format using ffmpeg."""
    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)

    command = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-codec:v", "libx264",
        "-codec:a", "aac",
        "-preset", "ultrafast",
        "-hls_time", "4",
        "-hls_playlist_type", "vod",
        "-hls_list_size", "0",
        "-f", "hls",
        "-hls_segment_filename", str(output_folder / "segment_%03d.ts"),
        str(output_folder / "index.m3u8"),
    ]

    subprocess.run(
        command,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )


def generate_thumbnail(video_path, thumbnail_path):
    """Generate a JPEG thumbnail from a video."""
    command = [
        "ffmpeg", "-y",
        "-ss", "00:00:01",
        "-i", str(video_path),
        "-frames:v", "1",
        "-q:v", "3",
        str(thumbnail_path),
    ]
    subprocess.run(
        command,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )


def process_video(filepath, filename):
    """Process uploaded videos in a background thread."""
    extension = Path(filename).suffix.lower().lstrip(".")
    if extension not in VIDEO_EXTENSIONS:
        return

    hls_folder = UPLOAD_FOLDER / f"{filename}_hls"
    thumbnail_path = UPLOAD_FOLDER / f"{filename}_thumb.jpg"

    try:
        convert_to_hls(filepath, hls_folder)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        app.logger.exception("Video conversion failed: %s", exc)

    try:
        generate_thumbnail(filepath, thumbnail_path)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        app.logger.exception("Thumbnail generation failed: %s", exc)


# ---------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------

def login_required():
    if "id" not in session:
        return redirect(url_for("login"))
    return None


def is_admin():
    return session.get("email", "").lower() == ADMIN_EMAIL


def get_owned_file(cursor, file_id, user_id, include_deleted=False):
    """Return a file only if it belongs to the logged-in user."""
    sql = "SELECT * FROM files WHERE id=%s AND user_id=%s"
    params = [file_id, user_id]
    if not include_deleted:
        sql += " AND deleted=0"
    cursor.execute(sql, tuple(params))
    return cursor.fetchone()


# ---------------------------------------------------------------------
# HOME, REGISTRATION, LOGIN, LOGOUT
# ---------------------------------------------------------------------

@app.route("/")
def home():
    return redirect(url_for("dashboard") if "id" in session else url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    msg = ""

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        raw_password = request.form.get("password", "")

        if not name or not email or not raw_password:
            msg = "Please fill in all fields."
        else:
            conn = get_db_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM users WHERE email=%s", (email,))
                if cursor.fetchone():
                    msg = "Account already exists."
                else:
                    password_hash = generate_password_hash(raw_password)
                    cursor.execute(
                        "INSERT INTO users (name, email, password) VALUES (%s, %s, %s)",
                        (name, email, password_hash),
                    )
                    conn.commit()
                    return redirect(url_for("login"))
            finally:
                conn.close()

    return render_template("auth/register.html", msg=msg)


@app.route("/login", methods=["GET", "POST"])
def login():
    msg = ""

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        conn = get_db_connection()
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM users WHERE email=%s", (email,))
            user = cursor.fetchone()
        finally:
            conn.close()

        if user and check_password_hash(user["password"], password):
            session.clear()
            session["id"] = user["id"]
            session["name"] = user["name"]
            session["email"] = user["email"]
            return redirect(url_for("dashboard"))

        msg = "Invalid email or password."

    return render_template("auth/login.html", msg=msg)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------
# SETTINGS
# ---------------------------------------------------------------------

@app.route("/settings", methods=["GET", "POST"])
def settings():
    auth_redirect = login_required()
    if auth_redirect:
        return auth_redirect

    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT IFNULL(SUM(size), 0) AS used FROM files "
            "WHERE user_id=%s AND deleted=0",
            (session["id"],),
        )
        used = float(cursor.fetchone()["used"] or 0)

        if request.method == "POST":
            old_password = request.form.get("old_password", "")
            new_password = request.form.get("new_password", "")

            if not new_password:
                flash("Please enter a new password.")
            else:
                cursor.execute(
                    "SELECT password FROM users WHERE id=%s",
                    (session["id"],),
                )
                user = cursor.fetchone()

                if user and check_password_hash(user["password"], old_password):
                    new_hash = generate_password_hash(new_password)
                    cursor.execute(
                        "UPDATE users SET password=%s WHERE id=%s",
                        (new_hash, session["id"]),
                    )
                    conn.commit()
                    flash("Password updated successfully.")
                else:
                    flash("Old password is incorrect.")
    finally:
        conn.close()

    return render_template("dashboard/settings.html", used=round(used, 2))


# ---------------------------------------------------------------------
# DASHBOARD
# ---------------------------------------------------------------------

@app.route("/dashboard")
def dashboard():
    auth_redirect = login_required()
    if auth_redirect:
        return auth_redirect

    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            "SELECT * FROM files WHERE user_id=%s AND deleted=0 ORDER BY id DESC",
            (session["id"],),
        )
        user_files = cursor.fetchall()

        cursor.execute(
            "SELECT IFNULL(SUM(size), 0) AS total FROM files "
            "WHERE user_id=%s AND deleted=0",
            (session["id"],),
        )
        total_size = float(cursor.fetchone()["total"] or 0)

        cursor.execute(
            "SELECT IFNULL(SUM(downloads), 0) AS total FROM files WHERE user_id=%s",
            (session["id"],),
        )
        downloads = int(cursor.fetchone()["total"] or 0)

        cursor.execute(
            """
            SELECT COUNT(shares.id) AS total
            FROM shares
            JOIN files ON shares.file_id = files.id
            WHERE files.user_id=%s
            """,
            (session["id"],),
        )
        shared = int(cursor.fetchone()["total"] or 0)
    finally:
        conn.close()

    return render_template(
        "dashboard/dashboard.html",
        files=user_files,
        used=total_size,
        total_files=len(user_files),
        total_size=total_size,
        downloads=downloads,
        shared=shared,
        total_storage=TOTAL_STORAGE,
    )


# ---------------------------------------------------------------------
# VIDEO STREAMING
# ---------------------------------------------------------------------

@app.route("/stream/<path:filename>")
def stream(filename):
    # The path is relative to uploads/, allowing HLS files in subfolders.
    if filename.endswith(".m3u8"):
        return send_from_directory(
            UPLOAD_FOLDER,
            filename,
            mimetype="application/vnd.apple.mpegurl",
        )

    if filename.endswith(".ts"):
        return send_from_directory(
            UPLOAD_FOLDER,
            filename,
            mimetype="video/mp2t",
        )

    return send_from_directory(UPLOAD_FOLDER, filename)


# ---------------------------------------------------------------------
# PDF EXPORT
# ---------------------------------------------------------------------

@app.route("/export_pdf", methods=["GET", "POST"])
def export_pdf():
    html = request.form.get("content") if request.method == "POST" else request.args.get("content")

    if not html:
        return "No HTML content provided.", 400

    try:
        pdf_data = pdfkit.from_string(html, False)
        return Response(
            pdf_data,
            mimetype="application/pdf",
            headers={"Content-Disposition": "inline; filename=export.pdf"},
        )
    except Exception as exc:
        app.logger.exception("PDF export failed")
        return f"PDF export failed: {exc}", 500


# ---------------------------------------------------------------------
# PROFILE
# ---------------------------------------------------------------------

@app.route("/profile", methods=["GET", "POST"])
def profile():
    auth_redirect = login_required()
    if auth_redirect:
        return auth_redirect

    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)

        if request.method == "POST":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()

            if not name or not email:
                flash("Name and email are required.")
            else:
                cursor.execute(
                    "SELECT id FROM users WHERE email=%s AND id<>%s",
                    (email, session["id"]),
                )
                if cursor.fetchone():
                    flash("That email address is already in use.")
                else:
                    cursor.execute(
                        "UPDATE users SET name=%s, email=%s WHERE id=%s",
                        (name, email, session["id"]),
                    )
                    conn.commit()
                    session["name"] = name
                    session["email"] = email
                    flash("Profile updated successfully.")

        cursor.execute("SELECT * FROM users WHERE id=%s", (session["id"],))
        user = cursor.fetchone()
    finally:
        conn.close()

    return render_template("dashboard/profile.html", user=user)


# ---------------------------------------------------------------------
# FILE UPLOAD
# ---------------------------------------------------------------------

@app.route("/upload", methods=["POST"])
def upload():
    auth_redirect = login_required()
    if auth_redirect:
        return auth_redirect

    if "file" not in request.files:
        flash("No file was selected.")
        return redirect(url_for("dashboard"))

    uploaded_file = request.files["file"]
    if not uploaded_file or not uploaded_file.filename:
        flash("No file was selected.")
        return redirect(url_for("dashboard"))

    safe_name = secure_filename(uploaded_file.filename)
    if not safe_name:
        return "Invalid filename.", 400

    filename = f"{uuid.uuid4().hex[:8]}_{safe_name}"
    filepath = UPLOAD_FOLDER / filename

    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            "SELECT IFNULL(SUM(size), 0) AS used FROM files "
            "WHERE user_id=%s AND deleted=0",
            (session["id"],),
        )
        used_mb = float(cursor.fetchone()["used"] or 0)

        uploaded_file.save(filepath)
        file_size_mb = filepath.stat().st_size / (1024 * 1024)

        if used_mb + file_size_mb > TOTAL_STORAGE:
            filepath.unlink(missing_ok=True)
            return "Storage limit exceeded (18 GB).", 413

        filetype = filepath.suffix.lower().lstrip(".")

        cursor.execute(
            """
            INSERT INTO files (user_id, filename, filepath, size, filetype)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (session["id"], filename, str(filepath), file_size_mb, filetype),
        )
        conn.commit()
    except Exception:
        filepath.unlink(missing_ok=True)
        raise
    finally:
        conn.close()

    threading.Thread(
        target=process_video,
        args=(str(filepath), filename),
        daemon=True,
    ).start()

    return "OK"


# ---------------------------------------------------------------------
# FILE EDITOR
# ---------------------------------------------------------------------

@app.route("/edit/<int:file_id>", methods=["GET", "POST"])
def edit_file(file_id):
    auth_redirect = login_required()
    if auth_redirect:
        return auth_redirect

    allowed = {"txt", "md", "html", "css", "js", "py", "json", "docx"}

    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        file_record = get_owned_file(cursor, file_id, session["id"])

        if not file_record:
            abort(404)

        if file_record["filetype"].lower() not in allowed:
            return "Editing is not allowed for this file type.", 400

        filepath = Path(file_record["filepath"])

        if request.method == "GET":
            if file_record["filetype"].lower() == "docx":
                with filepath.open("rb") as docx_file:
                    content = mammoth.convert_to_html(docx_file).value
            else:
                content = filepath.read_text(encoding="utf-8")

            return render_template(
                "dashboard/editor.html",
                file=file_record,
                content=content,
            )

        # Accept either JSON or standard form submissions.
        data = request.get_json(silent=True) if request.is_json else request.form
        content = data.get("content") if data else None

        if content is None:
            return jsonify({"status": "error", "message": "Content is missing."}), 400

        if file_record["filetype"].lower() == "docx":
            pandoc_path = shutil.which("pandoc")
            if not pandoc_path:
                return (
                    "Pandoc is required to save DOCX files. Install Pandoc "
                    "and make sure it is available in PATH.",
                    500,
                )

            temp_html = filepath.with_name(f"{filepath.stem}_temp_edit.html")
            try:
                temp_html.write_text(content, encoding="utf-8")
                result = subprocess.run(
                    [pandoc_path, str(temp_html), "-o", str(filepath)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode != 0:
                    app.logger.error("Pandoc error: %s", result.stderr)
                    return "DOCX conversion failed.", 500
            finally:
                temp_html.unlink(missing_ok=True)
        else:
            filepath.write_text(content, encoding="utf-8")

        return jsonify({
            "status": "success",
            "redirect": url_for("preview", file_id=file_id),
        })
    finally:
        conn.close()


# ---------------------------------------------------------------------
# FILE MANAGER
# ---------------------------------------------------------------------

@app.route("/files")
def files():
    auth_redirect = login_required()
    if auth_redirect:
        return auth_redirect

    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM files WHERE user_id=%s AND deleted=0 ORDER BY id DESC",
            (session["id"],),
        )
        user_files = cursor.fetchall()
    finally:
        conn.close()

    return render_template("dashboard/files.html", files=user_files)


# ---------------------------------------------------------------------
# FILE PREVIEW
# ---------------------------------------------------------------------

@app.route("/preview/<int:file_id>")
def preview(file_id):
    auth_redirect = login_required()
    if auth_redirect:
        return auth_redirect

    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        file_record = get_owned_file(cursor, file_id, session["id"])
    finally:
        conn.close()

    if not file_record:
        abort(404)

    content = ""
    extension = file_record["filetype"].lower()
    filepath = Path(file_record["filepath"])

    if extension == "docx":
        with filepath.open("rb") as docx_file:
            content = mammoth.convert_to_html(docx_file).value
    elif extension in {"txt", "md", "html", "css", "js", "py", "json"}:
        content = filepath.read_text(encoding="utf-8")

    rendered = render_template(
        "dashboard/preview.html",
        file=file_record,
        content=content,
    )
    return Response(rendered, headers={"Cache-Control": "no-store"})


@app.route("/uploads/<path:filename>")
def serve_upload(filename):
    # For authenticated access, prefer download/preview routes.
    auth_redirect = login_required()
    if auth_redirect:
        return auth_redirect
    return send_from_directory(UPLOAD_FOLDER, filename, conditional=True)


@app.route("/editor")
def editor():
    auth_redirect = login_required()
    if auth_redirect:
        return auth_redirect
    return render_template("dashboard/editor.html")


# ---------------------------------------------------------------------
# DOWNLOAD
# ---------------------------------------------------------------------

@app.route("/download/<int:file_id>")
def download(file_id):
    auth_redirect = login_required()
    if auth_redirect:
        return auth_redirect

    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        file_record = get_owned_file(cursor, file_id, session["id"])
        if not file_record:
            abort(404)

        cursor.execute(
            "UPDATE files SET downloads=downloads+1 WHERE id=%s AND user_id=%s",
            (file_id, session["id"]),
        )
        conn.commit()
    finally:
        conn.close()

    return send_file(
        file_record["filepath"],
        as_attachment=True,
        download_name=file_record["filename"],
    )


# ---------------------------------------------------------------------
# TRASH, RESTORE, DELETE
# ---------------------------------------------------------------------

@app.route("/delete/<int:file_id>", methods=["POST"])
def delete(file_id):
    auth_redirect = login_required()
    if auth_redirect:
        return auth_redirect

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE files SET deleted=1 WHERE id=%s AND user_id=%s AND deleted=0",
            (file_id, session["id"]),
        )
        conn.commit()
    finally:
        conn.close()

    return redirect(url_for("dashboard"))


@app.route("/trash")
def trash():
    auth_redirect = login_required()
    if auth_redirect:
        return auth_redirect

    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM files WHERE user_id=%s AND deleted=1 ORDER BY id DESC",
            (session["id"],),
        )
        user_files = cursor.fetchall()
    finally:
        conn.close()

    return render_template("dashboard/trash.html", files=user_files)


@app.route("/restore/<int:file_id>", methods=["POST"])
def restore(file_id):
    auth_redirect = login_required()
    if auth_redirect:
        return auth_redirect

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE files SET deleted=0 WHERE id=%s AND user_id=%s AND deleted=1",
            (file_id, session["id"]),
        )
        conn.commit()
    finally:
        conn.close()

    return redirect(url_for("trash"))


# ---------------------------------------------------------------------
# SHARING
# ---------------------------------------------------------------------

@app.route("/share/<int:file_id>", methods=["GET", "POST"])
def share(file_id):
    auth_redirect = login_required()
    if auth_redirect:
        return auth_redirect

    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        file_record = get_owned_file(cursor, file_id, session["id"])

        if not file_record:
            abort(404)

        link = None
        if request.method == "POST":
            try:
                days = int(request.form.get("expiry", "7"))
                if days < 1 or days > 365:
                    raise ValueError
            except ValueError:
                flash("Please select a valid expiry period.")
                return render_template(
                    "dashboard/share.html",
                    file=file_record,
                    link=None,
                )

            token = secrets.token_urlsafe(32)
            expiry = datetime.datetime.now() + datetime.timedelta(days=days)

            cursor.execute(
                "INSERT INTO shares (file_id, token, expiry) VALUES (%s, %s, %s)",
                (file_id, token, expiry),
            )
            conn.commit()
            link = request.host_url.rstrip("/") + url_for("public", token=token)

    finally:
        conn.close()

    return render_template("dashboard/share.html", file=file_record, link=link)


@app.route("/public/<token>")
def public(token):
    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT files.filepath, files.filename
            FROM shares
            JOIN files ON shares.file_id = files.id
            WHERE shares.token=%s AND shares.expiry > NOW() AND files.deleted=0
            """,
            (token,),
        )
        shared_file = cursor.fetchone()
    finally:
        conn.close()

    if not shared_file or not os.path.isfile(shared_file["filepath"]):
        return "Invalid or expired link.", 404

    return send_file(
        shared_file["filepath"],
        as_attachment=True,
        download_name=shared_file["filename"],
    )


# ---------------------------------------------------------------------
# ADMIN DASHBOARD
# ---------------------------------------------------------------------

@app.route("/admin")
def admin_required():
    auth_redirect = login_required()
    if auth_redirect:
        return auth_redirect

    if not is_admin():
        abort(403)

    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT COUNT(*) AS total FROM users")
        users_count = cursor.fetchone()["total"]

        cursor.execute("SELECT COUNT(*) AS total FROM files")
        files_count = cursor.fetchone()["total"]

        cursor.execute("SELECT IFNULL(SUM(size), 0) AS total FROM files")
        storage = cursor.fetchone()["total"]

        cursor.execute(
            """
            SELECT users.name, users.email,
                   COUNT(files.id) AS files,
                   IFNULL(SUM(files.size), 0) AS storage
            FROM users
            LEFT JOIN files ON users.id = files.user_id
            GROUP BY users.id, users.name, users.email
            ORDER BY users.id DESC
            """
        )
        users = cursor.fetchall()
    finally:
        conn.close()

    return render_template(
        "admin/admin.html",
        users_count=users_count,
        files_count=files_count,
        storage=storage,
        users=users,
    )


@app.route("/delete_permanent/<int:file_id>", methods=["POST"])
def delete_permanent(file_id):
    auth_redirect = login_required()
    if auth_redirect:
        return auth_redirect

    conn = get_db_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT filepath FROM files WHERE id=%s AND user_id=%s AND deleted=1",
            (file_id, session["id"]),
        )
        file_record = cursor.fetchone()

        if file_record:
            filepath = Path(file_record["filepath"])
            filename = filepath.name

            # Remove the original file, thumbnail, and generated HLS folder.
            filepath.unlink(missing_ok=True)
            (UPLOAD_FOLDER / f"{filename}_thumb.jpg").unlink(missing_ok=True)
            shutil.rmtree(UPLOAD_FOLDER / f"{filename}_hls", ignore_errors=True)

            cursor.execute(
                "DELETE FROM files WHERE id=%s AND user_id=%s AND deleted=1",
                (file_id, session["id"]),
            )
            conn.commit()
    finally:
        conn.close()

    return redirect(url_for("trash"))


# ---------------------------------------------------------------------
# ANALYTICS
# ---------------------------------------------------------------------

@app.route("/analytics")
def analytics():
    auth_redirect = login_required()
    if auth_redirect:
        return auth_redirect

    if not is_admin():
        abort(403)

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM users")
        users = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM files")
        files_count = cursor.fetchone()[0]

        cursor.execute("SELECT IFNULL(SUM(size), 0) FROM files")
        storage = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM files WHERE filetype IN ('jpg','png','jpeg','gif')"
        )
        images = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM files WHERE filetype IN ('mp4','mkv','mov')"
        )
        videos = cursor.fetchone()[0]
    finally:
        conn.close()

    return render_template(
        "admin/analytics.html",
        users=users,
        files=files_count,
        storage=storage,
        images=images,
        videos=videos,
    )


@app.route("/api/analytics")
def api_analytics():
    if "id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    if not is_admin():
        return jsonify({"error": "Forbidden"}), 403

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM users")
        users = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM files")
        files_count = cursor.fetchone()[0]

        cursor.execute("SELECT IFNULL(SUM(size), 0) FROM files")
        storage = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT DATE(uploaded_at), COUNT(*)
            FROM files
            GROUP BY DATE(uploaded_at)
            ORDER BY DATE(uploaded_at) DESC
            LIMIT 7
            """
        )
        uploads = cursor.fetchall()

        cursor.execute(
            """
            SELECT DATE(created_at), COUNT(*)
            FROM users
            GROUP BY DATE(created_at)
            ORDER BY DATE(created_at) DESC
            LIMIT 7
            """
        )
        growth = cursor.fetchall()
    finally:
        conn.close()

    return jsonify({
        "users": users,
        "files": files_count,
        "storage": float(storage or 0),
        "uploads": [
            {"date": str(row[0]), "count": row[1]} for row in uploads
        ],
        "growth": [
            {"date": str(row[0]), "count": row[1]} for row in growth
        ],
    })


# ---------------------------------------------------------------------
# ERROR HANDLERS
# ---------------------------------------------------------------------

@app.errorhandler(413)
def request_entity_too_large(_error):
    return "The uploaded file exceeds the 100 MB upload limit.", 413


# ---------------------------------------------------------------------
# RUN
# ---------------------------------------------------------------------

if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=os.getenv("FLASK_DEBUG", "1") == "1",
    )
