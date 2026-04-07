from flask import Flask, render_template, request, redirect, session
from dotenv import load_dotenv
import os


from database import get_cursor, get_db, create_tables
from utils import *

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "pitchpoint-secret-key")

create_tables()


# ============================================================
# ROUTES
# ============================================================

@app.route("/")
def home():
    process_results()

    template_data = get_common_template_data()
    upcoming, finished = get_matches()

    user_predictions = {}
    if "user_id" in session:
        user_predictions = get_user_predictions(session["user_id"])

    return render_template(
        "index.html",
        upcoming=upcoming,
        finished=finished[:10],
        user_predictions=user_predictions,
        **template_data
    )


@app.route("/predict", methods=["POST"])
def predict():
    if "user_id" not in session:
        return redirect("/login")

    try:
        match_id = int(request.form.get("match_id", "").strip())
        predicted_home = int(request.form.get("home", "").strip())
        predicted_away = int(request.form.get("away", "").strip())
    except:
        return redirect("/")

    home_team = request.form.get("home_team", "").strip()
    away_team = request.form.get("away_team", "").strip()

    if predicted_home < 0 or predicted_away < 0:
        return redirect("/")

    live_match = find_match_by_id(match_id)
    if not live_match or live_match.get("status") not in ["SCHEDULED", "TIMED"]:
        return redirect("/")

    cur = get_cursor()

    cur.execute("""
    SELECT prediction_id
    FROM Predictions
    WHERE user_id = %s AND match_id = %s
    """, (session["user_id"], match_id))
    existing = cur.fetchone()

    if existing:
        cur.execute("""
        UPDATE Predictions
        SET home_team = %s,
            away_team = %s,
            predicted_home = %s,
            predicted_away = %s
        WHERE user_id = %s AND match_id = %s
        """, (
            home_team,
            away_team,
            predicted_home,
            predicted_away,
            session["user_id"],
            match_id
        ))
    else:
        cur.execute("""
        INSERT INTO Predictions (
            user_id, match_id, home_team, away_team, predicted_home, predicted_away
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            session["user_id"],
            match_id,
            home_team,
            away_team,
            predicted_home,
            predicted_away
        ))

        cur.execute("""
        INSERT IGNORE INTO UserStats (user_id, total_predictions, total_winnings)
        VALUES (%s, 0, 0)
        """, (session["user_id"],))

        cur.execute("""
        UPDATE UserStats
        SET total_predictions = total_predictions + 1
        WHERE user_id = %s
        """, (session["user_id"],))

    get_db().commit()
    return redirect("/")


@app.route("/history")
def history():
    if "user_id" not in session:
        return redirect("/login")

    process_results()
    template_data = get_common_template_data()

    cur = get_cursor()
    cur.execute("""
    SELECT
        prediction_id,
        match_id,
        home_team,
        away_team,
        predicted_home,
        predicted_away,
        points,
        calculated
    FROM Predictions
    WHERE user_id = %s
    ORDER BY prediction_id DESC
    """, (session["user_id"],))
    predictions = cur.fetchall()

    return render_template(
        "history.html",
        predictions=predictions,
        **template_data
    )


@app.route("/leaderboard")
def leaderboard():
    process_results()
    template_data = get_common_template_data()

    return render_template(
        "leaderboard.html",
        leaderboard_rows=get_leaderboard(),
        **template_data
    )


@app.route("/chat")
def chat():
    process_results()
    template_data = get_common_template_data()

    return render_template(
        "chat.html",
        messages=get_chat(),
        **template_data
    )


@app.route("/chat/send", methods=["POST"])
def send_chat():
    if "user_id" not in session:
        return redirect("/login")

    message_text = request.form.get("message_text", "").strip()

    if not message_text:
        return redirect("/chat")

    if len(message_text) > 200:
        message_text = message_text[:200]

    cur = get_cursor()
    cur.execute("""
    INSERT INTO ChatMessages (user_id, message_text)
    VALUES (%s, %s)
    """, (session["user_id"], message_text))

    get_db().commit()
    return redirect("/chat")


@app.route("/delete-account", methods=["POST"])
def delete_account():
    if "user_id" not in session:
        return redirect("/login")

    cur = get_cursor()

    cur.execute("""
    DELETE FROM Users WHERE user_id = %s
    """, (session["user_id"],))

    get_db().commit()

    session.clear()
    return redirect("/")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        template_data = get_common_template_data()
        return render_template("login.html", **template_data)

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()

    if not username or not password:
        template_data = get_common_template_data()
        return render_template("login.html", **template_data)

    cur = get_cursor()
    cur.execute("""
    SELECT user_id, username
    FROM Users
    WHERE username = %s AND password = %s
    """, (username, password))
    user = cur.fetchone()

    if user:
        session["user_id"] = user["user_id"]
        return redirect("/")

    template_data = get_common_template_data()
    return render_template("login.html", **template_data)


@app.route("/signup", methods=["POST"])
def signup():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()

    if not username or not password:
        return redirect("/login")

    cur = get_cursor()

    try:
        cur.execute("""
        INSERT INTO Users (username, password)
        VALUES (%s, %s)
        """, (username, password))

        new_user_id = cur.lastrowid

        cur.execute("""
        INSERT INTO UserStats (user_id, total_predictions, total_winnings)
        VALUES (%s, 0, 0)
        """, (new_user_id,))

        get_db().commit()
        return redirect("/login")

    except:
        get_db().rollback()
        return redirect("/login")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

if __name__ == "__main__":
    app.run(debug=True)