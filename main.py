from functools import wraps
import os
from ftplib import FTP
import tempfile
import logging

from flask import Flask, render_template, request, Response
from werkzeug.utils import secure_filename

from secret import FTP_HOST, FTP_PASSWORD, FTP_PORT, FTP_USERNAME

app = Flask(__name__)  

logging.basicConfig(filename='cde_file_upload.log', encoding='utf-8', level=logging.DEBUG)

def check_auth(username, password):
    """This function is called to check if a username /
    password combination is valid.
    """
    return username == FTP_USERNAME and password == FTP_PASSWORD

def authenticate():
    """Sends a 401 response that enables basic auth"""
    return Response(
    'Could not verify your access level for that URL.\n'
    'You have to login with proper credentials', 401,
    {'WWW-Authenticate': 'Basic realm="Login Required"'})

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

def chdir(ftp, dir): 
    if directory_exists(ftp, dir) is False: # (or negate, whatever you prefer for readability)
        ftp.mkd(dir)
    ftp.cwd(dir)

# Check if directory exists (in current location)
def directory_exists(ftp, dir):
    filelist = []
    ftp.retrlines('LIST',filelist.append)
    for f in filelist:
        if f.split()[-1] == dir and f.upper().startswith('D'):
            return True
    return False

def upload_file_to_ftp(ftp, file_path, filename, user_name, target_path):

    chdir(ftp, user_name)
    logging.debug(f"  changed dir {user_name}")
    if target_path:
        chdir(ftp, target_path)
        logging.debug(f"  changed dir {target_path}")

    with open(file_path, 'rb') as file:
        ftp.storbinary('STOR ' + filename, file)

    logging.debug("  wrote file")



  
@app.route('/')
@requires_auth
def main():  
    logging.debug("/ endpoint")
    return render_template("Index.html") 


@app.route('/success', methods=['POST'])
def upload():
    logging.debug("Upload received")

    msg = "<h1>Uploaded Files</h1><ul>"

    try:

        target_folder = request.values.get("folder", "")
        user_name = request.values["user"]

        user_name = secure_filename(user_name)
        if target_folder:
            target_folder = secure_filename(target_folder)

        logging.debug(f"target_folder {target_folder}")
        logging.debug(f"user name {user_name}")

        with tempfile.TemporaryDirectory() as upload_dir:

            if 'files' not in request.files:
                return 'No files part of the request', 400

            files = request.files.getlist('files')

            logging.debug("Logging into FTP server")
            ftp = FTP()
            ftp.connect(FTP_HOST, FTP_PORT)
            ftp.login(FTP_USERNAME, FTP_PASSWORD)
            logging.debug("  login successful")

            for file in files:
                try:

                    logging.debug(f"Processing file {file.filename}")
                    if file.filename == '':
                        raise ValueError('One or more files do not have a name (probably uploaded empty file)')
                    
                    file_name = secure_filename(file.filename)

                    filepath = os.path.join(upload_dir, file_name)

                    file.save(filepath)
                    logging.debug("  saved")
                    upload_file_to_ftp(ftp, filepath, file_name, user_name, target_folder)
                    logging.debug("  uploaded")

                    msg += f"<li>{file_name}: Success"

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