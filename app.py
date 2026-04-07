#Imports needed for the application
from flask import Flask, render_template, request, redirect, session
from dotenv import load_dotenv
from database import get_cursor, get_db, create_tables
from utils import *
import os
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "secret")

#Calls/loads database.py to use in different routes
create_tables()

#Creates and renders index.html with matches via API
@app.route("/")
def home():
    process_results()

    upcoming, finished = get_matches()

    user_predictions = {}
    if "user_id" in session:
        user_predictions = get_user_predictions(session["user_id"])

    return render_template(
        "index.html",
        upcoming=upcoming,
        finished=finished[:10],
        user_predictions=user_predictions,
        **get_common_template_data()
    )

# Allows predictions to be be made and saved in the appropiate SQL table
@app.route("/predict", methods=["POST"])
def predict():
    if "user_id" not in session:
        return redirect("/login")
    try:
        match_id = int(request.form["match_id"])
        home = int(request.form["home"])
        away = int(request.form["away"])
    except:
        return redirect("/")

    if home < 0 or away < 0:
        return redirect("/")

    match = find_match_by_id(match_id)
    if not match or match["status"] not in ["SCHEDULED", "TIMED"]:
        return redirect("/")

    cur = get_cursor()

    cur.execute("SELECT * FROM Predictions WHERE user_id=%s AND match_id=%s",
                (session["user_id"], match_id))
    if cur.fetchone():
        cur.execute("""
        UPDATE Predictions
        SET predicted_home=%s, predicted_away=%s
        WHERE user_id=%s AND match_id=%s
        """, (home, away, session["user_id"], match_id))
    else:
        cur.execute("""
        INSERT INTO Predictions (user_id, match_id, home_team, away_team, predicted_home, predicted_away)
        VALUES (%s,%s,%s,%s,%s,%s)
        """, (
            session["user_id"],
            match_id,
            request.form["home_team"],
            request.form["away_team"],
            home,
            away
        ))

        cur.execute("""
        INSERT IGNORE INTO UserStats (user_id, total_predictions, total_winnings)
        VALUES (%s,0,0)
        """, (session["user_id"],))

        cur.execute("""
        UPDATE UserStats
        SET total_predictions = total_predictions + 1
        WHERE user_id=%s
        """, (session["user_id"],))

    get_db().commit()
    return redirect("/")

#Renders history.html with retriving from preditions table
@app.route("/history")
def history():
    if "user_id" not in session:
        return redirect("/login")
    
    process_results()
    cur = get_cursor()
    cur.execute("""
    SELECT *
    FROM Predictions
    WHERE user_id=%s
    ORDER BY prediction_id DESC
    """, (session["user_id"],))

    return render_template(
        "history.html",
        predictions=cur.fetchall(),
        **get_common_template_data()
    )

#Compares user points and creates leaderboard
@app.route("/leaderboard")
def leaderboard():
    process_results()

    return render_template(
        "leaderboard.html",
        leaderboard_rows=get_leaderboard(),
        **get_common_template_data()
    )

#Allows chat messages to be retrived from table
@app.route("/chat")
def chat():
    process_results()

    return render_template(
        "chat.html",
        messages=get_chat(),
        **get_common_template_data()
    )

#Chat_Message table stores user input from chat.html
@app.route("/chat/send", methods=["POST"])
def send_chat():

    if "user_id" not in session:
        return redirect("/login")

    text = request.form.get("message_text", "").strip()

    if text:
        cur = get_cursor()
        cur.execute("""
        INSERT INTO ChatMessages (user_id, message_text)
        VALUES (%s,%s)
        """, (session["user_id"], text[:200]))
        get_db().commit()

    return redirect("/chat")

# Uses delete SQL of the logged in account to remove data of the user_id

@app.route("/delete-account", methods=["POST"])
def delete_account():
    if "user_id" not in session:
        return redirect("/login")

    cur = get_cursor()
    cur.execute("DELETE FROM Users WHERE user_id=%s", (session["user_id"],))
    get_db().commit()

    session.clear()
    return redirect("/")

#Checks user's credientals to ensure an account exists
@app.route("/login", methods=["GET", "POST"])

def login():
    if request.method == "GET":
        return render_template("login.html", **get_common_template_data())
    username = request.form.get("username", "")
    password = request.form.get("password", "")

    cur = get_cursor()
    cur.execute("""
    SELECT user_id
    FROM Users
    WHERE username=%s AND password=%s
    """, (username, password))

    user = cur.fetchone()

    if user:
        session["user_id"] = user["user_id"]
        return redirect("/")
    return render_template("login.html", **get_common_template_data())

# Creates an account and stores username and password along with a user_id in Users table
@app.route("/signup", methods=["POST"])
def signup():
    username = request.form.get("username", "")
    password = request.form.get("password", "")

    if not username or not password:
        return redirect("/login")
    cur = get_cursor()

    try:
        cur.execute("""
        INSERT INTO Users (username, password)
        VALUES (%s,%s)
        """, (username, password))
        user_id = cur.lastrowid

        cur.execute("""
        INSERT INTO UserStats (user_id, total_predictions, total_winnings)
        VALUES (%s,0,0)
        """, (user_id,))

        get_db().commit()
    except:
        get_db().rollback()
    return redirect("/login")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

if __name__ == "__main__":
    app.run(debug=True)