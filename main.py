from distutils.log import debug
from fileinput import filename
import os
from flask import *  
from ftplib import FTP
import tempfile
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)  

# FTP server configuration
FTP_HOST = os.environ["FTP_HOST"]
FTP_PORT = 21
FTP_USERNAME = os.environ["FTP_USER"]
FTP_PASSWORD = os.environ["FTP_PASS"]
FTP_DIRECTORY = os.environ["FTP_PATH"]

def upload_file_to_ftp(file_path, filename, target_path):
    ftp = FTP()
    ftp.connect(FTP_HOST, FTP_PORT)
    ftp.login(FTP_USERNAME, FTP_PASSWORD)
    ftp.cwd(os.path.join(FTP_DIRECTORY, target_path))

    with open(file_path, 'rb') as file:
        ftp.storbinary('STOR ' + filename, file)

    ftp.quit()


  
@app.route('/')  
def main():  
    return render_template("index.html") 


@app.route('/success', methods=['POST'])
def upload():

    try:

        target_folder = request.data.get("folder")
        # TODO validation

        

        with tempfile.TemporaryDirectory() as upload_dir:

            if 'files' not in request.files:
                return 'No files part in the request', 400

            files = request.files.getlist('files')

            for file in files:
                if file.filename == '':
                    return 'One or more files do not have a name', 400

                filepath = os.path.join(upload_dir, secure_filename(file.filename))

                file.save(filepath)
                upload_file_to_ftp(filepath, secure_filename(file.filename), target_folder)

            msg = "Success"

    except Exception as e:

        msg = f"{e.__class__}: {e}"


    return render_template("Success.html", length = len(files), msg=msg)   
  
  
if __name__ == '__main__':  
    app.run(debug=True)