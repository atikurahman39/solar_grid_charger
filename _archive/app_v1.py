from flask import Flask, render_template
from database import get_latest_data

app = Flask(__name__)


@app.route("/")
def home():
    latest = get_latest_data()
    return render_template("dashboard.html", latest=latest)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
