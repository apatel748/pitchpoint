from dotenv import load_dotenv
import os
import pymysql

load_dotenv()

db = None

def get_db():
    global db

    try:
        if db:
            db.ping(reconnect=True)
            return db
    except:
        pass

    db = pymysql.connect(
        host=os.getenv("MYSQLHOST"),
        user=os.getenv("MYSQLUSER"),
        password=os.getenv("MYSQLPASSWORD"),
        database=os.getenv("MYSQLDATABASE"),
        port=int(os.getenv("MYSQLPORT")),
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False
    )
    return db


def get_cursor():
    return get_db().cursor()


# ============================================================
# TABLE CREATION
# ============================================================

def create_tables():
    cur = get_cursor()

    # USERS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS Users (
        user_id INT AUTO_INCREMENT PRIMARY KEY,
        username VARCHAR(50) UNIQUE NOT NULL,
        password VARCHAR(100) NOT NULL
    )
    """)

    # PREDICTIONS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS Predictions (
        prediction_id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        match_id INT NOT NULL,
        home_team VARCHAR(100) NOT NULL,
        away_team VARCHAR(100) NOT NULL,
        predicted_home INT NOT NULL,
        predicted_away INT NOT NULL,
        points INT DEFAULT NULL,
        calculated BOOLEAN DEFAULT FALSE,
        UNIQUE(user_id, match_id),
        FOREIGN KEY (user_id) REFERENCES Users(user_id) ON DELETE CASCADE
    )
    """)

    # CHAT MESSAGES
    cur.execute("""
    CREATE TABLE IF NOT EXISTS ChatMessages (
        message_id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        message_text VARCHAR(200) NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES Users(user_id) ON DELETE CASCADE
    )
    """)

    # MATCH RESULTS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS MatchResults (
        match_id INT PRIMARY KEY,
        home_team VARCHAR(100) NOT NULL,
        away_team VARCHAR(100) NOT NULL,
        home_score INT NOT NULL,
        away_score INT NOT NULL
    )
    """)

    # USER STATS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS UserStats (
        user_id INT PRIMARY KEY,
        total_predictions INT DEFAULT 0,
        total_winnings INT DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES Users(user_id) ON DELETE CASCADE
    )
    """)

    get_db().commit()