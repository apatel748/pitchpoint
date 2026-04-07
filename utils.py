from database import get_cursor, get_db
from flask import session
import requests
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("API_KEY")


def get_badge(points):
    if points >= 100:
        return "Gold"
    if points >= 50:
        return "Silver"
    return "Bronze"


def safe_request_json(url, headers=None, params=None):
    try:
        response = requests.get(url, headers=headers, params=params, timeout=15)
        response.raise_for_status()
        return response.json()
    except:
        return {}


def get_matches():
    url = "https://api.football-data.org/v4/matches"
    headers = {"X-Auth-Token": API_KEY}

    data = safe_request_json(url, headers=headers)
    matches = data.get("matches", [])

    upcoming = []
    finished = []

    for match in matches:
        status = match.get("status")

        # logos
        if "homeTeam" in match:
            match["homeTeam"]["crest"] = match["homeTeam"].get("crest")
        if "awayTeam" in match:
            match["awayTeam"]["crest"] = match["awayTeam"].get("crest")

        # date formatting
        utc_date_str = match.get("utcDate")
        if utc_date_str:
            try:
                dt = datetime.fromisoformat(utc_date_str.replace('Z', '+00:00'))
                match["formatted_date"] = dt.strftime('%b %d, %Y at %H:%M')
            except:
                match["formatted_date"] = "TBA"
        else:
            match["formatted_date"] = "TBA"

        if status in ["SCHEDULED", "TIMED"]:
            upcoming.append(match)
        elif status == "FINISHED":
            finished.append(match)

    upcoming.sort(key=lambda x: x.get("utcDate", ""))
    finished.sort(key=lambda x: x.get("utcDate", ""), reverse=True)

    return upcoming, finished


def find_match_by_id(match_id):
    upcoming, finished = get_matches()

    for match in upcoming + finished:
        if str(match.get("id")) == str(match_id):
            return match

    return None

def calc_points(predicted_home, predicted_away, real_home, real_away):
    if predicted_home == real_home and predicted_away == real_away:
        return 5

    predicted_diff = predicted_home - predicted_away
    real_diff = real_home - real_away

    if predicted_diff > 0 and real_diff > 0:
        return 3
    if predicted_diff < 0 and real_diff < 0:
        return 3
    if predicted_diff == 0 and real_diff == 0:
        return 3

    return 0


def process_results():
    _, finished = get_matches()
    cur = get_cursor()

    for match in finished:
        full_time = match.get("score", {}).get("fullTime", {})
        real_home = full_time.get("home")
        real_away = full_time.get("away")

        if real_home is None or real_away is None:
            continue

        match_id = match.get("id")
        home_team = match.get("homeTeam", {}).get("name", "")
        away_team = match.get("awayTeam", {}).get("name", "")

        cur.execute("""
        INSERT IGNORE INTO MatchResults (
            match_id, home_team, away_team, home_score, away_score
        )
        VALUES (%s, %s, %s, %s, %s)
        """, (
            match_id,
            home_team,
            away_team,
            real_home,
            real_away
        ))

        cur.execute("""
        SELECT prediction_id, user_id, predicted_home, predicted_away
        FROM Predictions
        WHERE match_id = %s AND calculated = FALSE
        """, (match_id,))
        prediction_rows = cur.fetchall()

        for row in prediction_rows:
            pts = calc_points(
                row["predicted_home"],
                row["predicted_away"],
                real_home,
                real_away
            )

            cur.execute("""
            UPDATE Predictions
            SET points = %s, calculated = TRUE
            WHERE prediction_id = %s
            """, (pts, row["prediction_id"]))

            cur.execute("""
            INSERT IGNORE INTO UserStats (user_id, total_predictions, total_winnings)
            VALUES (%s, 0, 0)
            """, (row["user_id"],))

            cur.execute("""
            UPDATE UserStats
            SET total_winnings = total_winnings + %s
            WHERE user_id = %s
            """, (
                1 if pts > 0 else 0,
                row["user_id"]
            ))

    get_db().commit()

def get_user_summary():
    if "user_id" not in session:
        return {
            "username": None,
            "total_points": 0,
            "badge_name": "Bronze",
            "total_predictions": 0,
            "total_winnings": 0
        }

    cur = get_cursor()

    cur.execute("""
    SELECT
        u.username,
        COALESCE(p.total_points, 0) AS total_points,
        COALESCE(s.total_predictions, 0) AS total_predictions,
        COALESCE(s.total_winnings, 0) AS total_winnings
    FROM Users u
    LEFT JOIN (
        SELECT user_id, SUM(COALESCE(points, 0)) AS total_points
        FROM Predictions
        GROUP BY user_id
    ) p ON u.user_id = p.user_id
    LEFT JOIN UserStats s ON u.user_id = s.user_id
    WHERE u.user_id = %s
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


def get_common_template_data():
    return get_user_summary()


def get_user_predictions(user_id):
    cur = get_cursor()

    cur.execute("""
    SELECT *
    FROM Predictions
    WHERE user_id = %s
    """, (user_id,))

    predictions = {}
    for row in cur.fetchall():
        predictions[row["match_id"]] = row

    return predictions


def get_leaderboard():
    cur = get_cursor()

    cur.execute("""
    SELECT
        u.username,
        COALESCE(p.total_points, 0) AS total_points,
        COALESCE(s.total_predictions, 0) AS total_predictions,
        COALESCE(s.total_winnings, 0) AS total_winnings
    FROM Users u
    LEFT JOIN (
        SELECT user_id, SUM(COALESCE(points, 0)) AS total_points
        FROM Predictions
        GROUP BY user_id
    ) p ON u.user_id = p.user_id
    LEFT JOIN UserStats s ON u.user_id = s.user_id
    ORDER BY total_points DESC, u.username ASC
    """)

    rows = cur.fetchall()

    for row in rows:
        row["badge"] = get_badge(row["total_points"])

    return rows


def get_chat():
    cur = get_cursor()

    cur.execute("""
    SELECT
        c.message_text,
        c.created_at,
        u.username,
        COALESCE(p.total_points, 0) AS total_points
    FROM ChatMessages c
    JOIN Users u ON c.user_id = u.user_id
    LEFT JOIN (
        SELECT user_id, SUM(COALESCE(points, 0)) AS total_points
        FROM Predictions
        GROUP BY user_id
    ) p ON u.user_id = p.user_id
    ORDER BY c.message_id ASC
    """)

    rows = cur.fetchall()

    for row in rows:
        row["badge"] = get_badge(row["total_points"])

    return rows