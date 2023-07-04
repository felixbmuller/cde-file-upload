from functools import wraps
from ftplib import FTP
import tempfile
import logging
from typing import Tuple, List
import pathlib

from flask import Flask, render_template, request, Response
from werkzeug.utils import secure_filename
from werkzeug.datastructures.file_storage import FileStorage

from secret import FTP_HOST, FTP_PORT

app = Flask(__name__)  

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


def is_directory(ftp: FTP, directory: str):
    """Check if this directory exists in the current ftp folder."""
    filelist: List[str] = []
    # execute 'ls -l' on the ftp server
    ftp.retrlines('LIST', filelist.append)
    for f in filelist:
        # one line looks like
        # drwxrwxr-x 2 2023_PfingstAkademie akademien 0 Jun 7 22:45 DirectoryName
        bits = f.split()[0]
        name = f.split()[-1]
        if name == directory:
            if bits.upper().startswith('D'):
                return True
            raise ValueError(f"Can not create directory {name}: File exists.")
    return False


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
def main():  
    logging.debug("/ endpoint")
    return render_template("Index.html")


@app.route('/success', methods=['POST'])
@requires_auth
def upload():
    logging.debug("Upload received")

    msg = "<h1>Uploaded Files</h1><ul>"

    try:
        user_name = secure_filename(request.values["user"])
        if target_folder := request.values.get("folder", ""):
            target_folder = secure_filename(target_folder)

        logging.debug(f"target_folder {target_folder}")
        logging.debug(f"user name {user_name}")

        with tempfile.TemporaryDirectory() as upload_dir:

            if 'files' not in request.files:
                return 'No files part of the request', 400

            files: List[FileStorage] = request.files.getlist('files')

            logging.debug("Logging into FTP server")
            ftp = FTP()
            ftp.connect(FTP_HOST, FTP_PORT)
            ftp.login(*get_credentials())
            logging.debug("  login successful")

            # create personal directory for current user
            if not is_directory(ftp, user_name):
                ftp.mkd(user_name)
            ftp.cwd(user_name)
            logging.debug(f"  changed dir {user_name}")

            # create subdirectory in personal user directory
            if target_folder:
                if not is_directory(ftp, target_folder):
                    ftp.mkd(target_folder)
                ftp.cwd(target_folder)
                logging.debug(f"  changed dir {target_folder}")

            for file in files:
                try:
                    logging.debug(f"Processing file {file.filename}")
                    if not file.filename:
                        raise ValueError('One or more files do not have a name (probably uploaded empty file)')

                    path = store_file(pathlib.Path(upload_dir), file)
                    upload_file(ftp, path)

                    msg += f"<li>{file.filename}: Success"
                except Exception as e:
                    logging.debug(f"exception {e.__class__}: {e}")
                    msg += f"<li>{file.filename}: {e.__class__.__name__}: {e}"

    except Exception as e:
        logging.debug(f"{e.__class__}: {e}")
        return f"Something went wrong<br> {e.__class__}: {e}", 500

    msg += "</ul>"

    ftp.quit()

    logging.debug("success")

    return msg, 200
  
  
if __name__ == '__main__':  
    app.run(debug=True)
