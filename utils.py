from database import get_cursor, get_db
from flask import session
import requests
from datetime import datetime
import os
from dotenv import load_dotenv
load_dotenv()

#Loads functions used throughout the application with the use of football-data.org API
API_KEY = os.getenv("API_KEY")

def get_badge(points):
    if points >= 100:
        return "Gold"
    if points >= 50:
        return "Silver"
    return "Bronze"


#Safe handling of calling the API of any errors
def safe_request_json(url, headers=None):
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        return r.json()
    except:
        return {}

#Function to call the API for the soccer matches with metadata (time, logo, status)
def get_matches():
    url = "https://api.football-data.org/v4/matches"
    headers = {"X-Auth-Token": API_KEY}
    data = safe_request_json(url, headers)
    matches = data.get("matches", [])

    upcoming = []
    finished = []

    for m in matches:
        status = m.get("status")
        if "homeTeam" in m:
            m["homeTeam"]["crest"] = m["homeTeam"].get("crest")
        if "awayTeam" in m:
            m["awayTeam"]["crest"] = m["awayTeam"].get("crest")
        date = m.get("utcDate")
        if date:
            try:
                d = datetime.fromisoformat(date.replace("Z", "+00:00"))
                m["formatted_date"] = d.strftime("%b %d, %Y %H:%M")
            except:
                m["formatted_date"] = "TBA"
        else:
            m["formatted_date"] = "TBA"

        if status in ["SCHEDULED", "TIMED"]:
            upcoming.append(m)
        elif status == "FINISHED":
            finished.append(m)

    upcoming.sort(key=lambda x: x.get("utcDate", ""))
    finished.sort(key=lambda x: x.get("utcDate", ""), reverse=True)

    return upcoming, finished

#Allows identifying matches by id in database
def find_match_by_id(match_id):
    upcoming, finished = get_matches()
    for m in upcoming + finished:
        if str(m.get("id")) == str(match_id):
            return m
    return None


#The match of predictions/real home/away scores into points
def calc_points(ph, pa, rh, ra):
    if ph == rh and pa == ra:
        return 5

    if (ph - pa > 0 and rh - ra > 0) or (ph - pa < 0 and rh - ra < 0) or (ph - pa == 0 and rh - ra == 0):
        return 3

    return 0

# Processes matches final score into points assigned to users in railway sql table
def process_results():
    _, finished = get_matches()
    cur = get_cursor()

    for m in finished:
        ft = m.get("score", {}).get("fullTime", {})
        rh = ft.get("home")
        ra = ft.get("away")
        if rh is None or ra is None:
            continue
        match_id = m.get("id")

        cur.execute("""
        INSERT IGNORE INTO MatchResults (match_id, home_team, away_team, home_score, away_score)
        VALUES (%s,%s,%s,%s,%s)
        """, (
            match_id,
            m.get("homeTeam", {}).get("name", ""),
            m.get("awayTeam", {}).get("name", ""),
            rh,
            ra
        ))

        cur.execute("""
        SELECT prediction_id, user_id, predicted_home, predicted_away
        FROM Predictions
        WHERE match_id=%s AND calculated=FALSE
        """, (match_id,))

        for row in cur.fetchall():
            pts = calc_points(row["predicted_home"], row["predicted_away"], rh, ra)

            cur.execute("""
            UPDATE Predictions
            SET points=%s, calculated=TRUE
            WHERE prediction_id=%s
            """, (pts, row["prediction_id"]))

            cur.execute("""
            INSERT IGNORE INTO UserStats (user_id, total_predictions, total_winnings)
            VALUES (%s,0,0)
            """, (row["user_id"],))

            cur.execute("""
            UPDATE UserStats
            SET total_winnings = total_winnings + %s
            WHERE user_id=%s
            """, (1 if pts > 0 else 0, row["user_id"]))

    get_db().commit()

# Retrives logged in user's data from sql tables such as name, predictions, and stats (points, winnings, badge) 
def get_user_summary():
    if "user_id" not in session:
        return {
            "username": None,
            "total_points": 0,
            "badge_name": "Bronze",
            "total_predictions": 0,
            "total_winnings": 0
        }

    #Uses LEFT JOIN to include the user's predictions and userstats table data
    cur = get_cursor()
    cur.execute("""
    SELECT u.username,
           COALESCE(p.total_points,0) AS total_points,
           COALESCE(s.total_predictions,0) AS total_predictions,
           COALESCE(s.total_winnings,0) AS total_winnings
    FROM Users u
    LEFT JOIN (
        SELECT user_id, SUM(COALESCE(points,0)) AS total_points
        FROM Predictions GROUP BY user_id
    ) p ON u.user_id=p.user_id
    LEFT JOIN UserStats s ON u.user_id=s.user_id
    WHERE u.user_id=%s
    """, (session["user_id"],))
    row = cur.fetchone()
    
    if not row:
        return {
            "username": None,
            "total_points": 0,
            "badge_name": "Bronze",
            "total_predictions": 0,
            "total_winnings": 0
        }
    return {
        "username": row["username"],
        "total_points": row["total_points"],
        "badge_name": get_badge(row["total_points"]),
        "total_predictions": row["total_predictions"],
        "total_winnings": row["total_winnings"]
    }

#simple quick function
def get_common_template_data():
    return get_user_summary()


#Returns the user's prediction table data
def get_user_predictions(user_id):
    cur = get_cursor()
    cur.execute("SELECT * FROM Predictions WHERE user_id=%s", (user_id,))
    data = {}
    for r in cur.fetchall():
        data[r["match_id"]] = r
    return data

#Looks at the total points of all user's and retrives a ordered leaderbord
def get_leaderboard():
    cur = get_cursor()
    cur.execute("""
    SELECT u.username,
           COALESCE(p.total_points,0) AS total_points,
           COALESCE(s.total_predictions,0) AS total_predictions,
           COALESCE(s.total_winnings,0) AS total_winnings
    FROM Users u
    LEFT JOIN (
        SELECT user_id, SUM(COALESCE(points,0)) AS total_points
        FROM Predictions GROUP BY user_id
    ) p ON u.user_id=p.user_id
    LEFT JOIN UserStats s ON u.user_id=s.user_id
    ORDER BY total_points DESC
    """)

    rows = cur.fetchall()
    for r in rows:
        r["badge"] = get_badge(r["total_points"])
    return rows

#Retrives chat_message table and relevant information displayed on the message
def get_chat():
    cur = get_cursor()
    cur.execute("""
    SELECT c.message_text, c.created_at, u.username,
           COALESCE(p.total_points,0) AS total_points
    FROM ChatMessages c
    JOIN Users u ON c.user_id=u.user_id
    LEFT JOIN (
        SELECT user_id, SUM(COALESCE(points,0)) AS total_points
        FROM Predictions GROUP BY user_id
    ) p ON u.user_id=p.user_id
    ORDER BY c.message_id ASC
    """)

    rows = cur.fetchall()
    for r in rows:
        r["badge"] = get_badge(r["total_points"])
    return rows