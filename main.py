from functools import wraps
from ftplib import FTP
import ftplib
import tempfile
import logging
from typing import Tuple, List
import pathlib

from flask import Flask, render_template, request, Response
from werkzeug.utils import secure_filename
from werkzeug.datastructures.file_storage import FileStorage

from secret import FTP_HOST, FTP_PORT


TEMPLATE_DIR_NAME = "Template"

app = Flask(__name__)
app.jinja_env.add_extension("jinja2.ext.loopcontrols")

logging.basicConfig(filename='cde_file_upload.log', encoding='utf-8', level=logging.DEBUG)


def get_credentials() -> Tuple[str, str]:
    """Extract credentials from request state."""
    if request.authorization:
        return request.authorization.username, request.authorization.password
    return request.values.get("user", ""), request.values.get("password", "")


def check_auth(username: str, password: str) -> bool:
    """Check authorization with username/password against the ftp server."""
    ftp = FTP()

    try:
        ftp.connect(FTP_HOST, FTP_PORT)
        ftp.login(username, password)
        ftp.quit()
    except Exception:
        ftp.quit()
        return False
    else:
        return True


def authenticate():
    """Sends a 401 response that enables basic auth"""
    return Response(
    'Could not verify your access level for that URL.\n'
    'You have to login with proper credentials', 401,
    {'WWW-Authenticate': 'Basic realm="Login Required"'})


def requires_auth(f):
    """Decorate an endpoint which requires authorization."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not check_auth(*get_credentials()):
            return authenticate()
        return f(*args, **kwargs)
    return decorated


def get_ftp_connection() -> ftplib.FTP:
    ftp = FTP()
    ftp.connect(FTP_HOST, FTP_PORT)
    ftp.login(*get_credentials())
    return ftp


def store_file(directory: pathlib.Path, file: FileStorage) -> pathlib.Path:
    """Save the file in the directory on the current hard-drive."""
    name = secure_filename(file.filename)
    path = directory / name

    file.save(path)
    logging.debug("  saved")
    return path


def upload_file(ftp: FTP, filepath: pathlib.Path):
    """Upload a file from a given path to the ftp."""
    with open(filepath, 'rb') as file:
        ftp.storbinary(f'STOR {filepath.name}', file)
    logging.debug("  uploaded")

  
@app.route('/')
@requires_auth
def index():
    return view_directory()

def sort_directory_entries(entry):

    type = entry[1]["type"]

    if type == "pdir":
        return 0
    elif type == "dir":
        return 1
    else:
        return 2
    
def handle_exception(e, status=400):
    return render_template("Error.html", str(e)), status

@app.route('/view')
@app.route('/view/')
@app.route('/view/<path:directory>')
@requires_auth
def view_directory(directory: str = "", errors: List[Tuple[str, str, str]] = None):
    """View the content of a directory on the ftp server.

    :param directory: The path to the directory which shall be displayed.
    :param errors: A list of errors which may appear during the file upload.
    """
    errors = errors or []
    # create a pseudo absolute path to utilize pathlib
    directory = pathlib.Path("/" + directory.lstrip("/"))
    ftp = get_ftp_connection()
    # retrieve the content of the directory
    try:
        content = list(ftp.mlsd(path=str(directory), facts=["type"]))
    except ftplib.all_errors as e:
        return handle_exception(e)
    ftp.quit()

    # Sort and filter entries
    content = sorted(content, key=sort_directory_entries)
    if directory == "":
        content = [c for c in content if c[0] != TEMPLATE_DIR_NAME]

    parent = directory.parent
    # guess the connected event from the auth username
    event, _ = get_credentials()
    return render_template(
        "Index.html", **{"cwd": str(directory), "parent": str(parent), "content": content,
                         "errors": errors, "event": event, "template_dir_name": TEMPLATE_DIR_NAME})

def process_name(name):
    name = secure_filename(name)
    name = name.replace(" ", "_").replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return name

@app.route('/create', methods=['POST'])
@requires_auth
def create_directory():
    """Create a new directory on the ftp server.

    This requires that the parent directory of the new subdirectory does already exist.
    """
    if 'parent' not in request.values:
        return handle_exception('Keinen Elternordner für das neue Verzeichnis angegeben.')
    if 'directory_name' not in request.values:
        return handle_exception('Keinen Namen für das neue Verzeichnis angegeben.')
    
    # create a pseudo absolute path to utilize pathlib
    parent = pathlib.Path(request.values["parent"])
    name = process_name(request.values["directory_name"])

    ftp = get_ftp_connection()

    # check that the parent directory already exists
    try:
        ftp.cwd(str(parent))
    except ftplib.all_errors as e:
        return handle_exception(f"Fehler: {e}")
    
    new = parent / name
    if new == parent:
        return handle_exception(f"Fehler: Neuer Ordner gleicht Elternordner: {new}")
    ftp.mkd(str(new))
    
    if request.values["parent"] == "":
        try:
            # Creating a folder at top-level -> clone template folder

            template_subdirs = ftp.mlsd(TEMPLATE_DIR_NAME, facts=["type"])
            template_subdirs = [dir 
                                for dir, facts in template_subdirs 
                                if (dir not in [".", ".."] and facts["type"] == "dir")]

            ftp.cwd(str(new))

            for s in template_subdirs:
                ftp.mkd(s)
        except Exception as e:
            # do not bother the user when the template folder does not exist, just don't clone it
            logging.debug(f"failed to clone template: {e.__class__}: {e}")
    
    ftp.quit()
    return view_directory(str(new))


@app.route('/upload', methods=['POST'])
@requires_auth
def upload_files():
    """Upload files to the ftp server.

    This requires that the upload directory does already exist.
    """
    if not request.files.get("files"):
        return handle_exception('Keine Dateien zum Hochladen ausgewählt.', status=400)
    if 'upload_directory' not in request.values:
        return handle_exception('Keinen Zielordner zum Hochladen angegeben.', status=400)
    # create a pseudo absolute path to utilize pathlib
    directory = pathlib.Path(request.values["upload_directory"])
    ftp = get_ftp_connection()

    # check that the upload directory already exists
    try:
        ftp.cwd(str(directory))
    except ftplib.all_errors as e:
        return handle_exception(f"Fehler: {e}", status=400)

    errors = []
    with tempfile.TemporaryDirectory() as upload_dir:
        files: List[FileStorage] = request.files.getlist('files')
        for file in files:
            try:
                logging.debug(f"Processing file {file.filename}")
                if not file.filename:
                    raise ValueError('One or more files do not have a name (probably uploaded empty file)')
                local_path = store_file(pathlib.Path(upload_dir), file)
                upload_file(ftp, local_path)
            except Exception as e:
                logging.debug(f"exception {e.__class__}: {e}")
                errors.append((file.filename, e.__class__.__name__, e))
    ftp.quit()
    return view_directory(str(directory), errors=errors)
  
  
if __name__ == '__main__':  
    app.run(debug=True)
