""" price_log_service.py """
from flask import send_from_directory, Flask

app: Flask = Flask(__name__)


@app.route("/<path:path>")
def root(path):
    """root handler"""
    return send_from_directory("log", path)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8998)
