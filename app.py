import os
import re
import sqlite3
import time
from datetime import datetime, timezone

import requests
from flask import Flask, render_template, jsonify, request, redirect, url_for, session

APP = Flask(__name__)

APP.secret_key = os.environ.get(
    "SECRET_KEY",
    "change-this-secret-key"
)

DB = os.environ.get(
    "DATABASE_PATH",
    "premove_legends.db"
)

CLUB_URL = os.environ.get(
    "CLUB_URL",
    "https://link.chess.com/club/W6nZgx"
)

CLUB_SLUG = os.environ.get(
    "CLUB_SLUG",
    "premove-legends"
)

TOURNAMENT_URL = os.environ.get(
    "TOURNAMENT_URL",
    "https://www.chess.com/play/arena/31104118"
)

ADMIN_PASSWORD = os.environ.get(
    "ADMIN_PASSWORD",
    "legend123"
)

UA = os.environ.get(
    "CHESS_API_USER_AGENT",
    "PremoveLegendsDashboard/1.0 (contact: replace-with-your-email@example.com)"
)


# ---------------------------------------------------------
# INITIAL PLAYERS
# ---------------------------------------------------------

SEED = [
    ("blinking_blunders", 2117, 2117, 2574, 2567),
    ("sriwarior", 1992, 1992, 1743, 1606),
    ("premove-legends", 1704, 1704, 1372, 0),
    ("harrypotterkaelenaetheris", 1640, 1640, 1506, 1266),
    ("phantomvertex", 1160, 1160, 994, 1055),
    ("shuttleblitz", 1105, 1105, 897, 809),
    ("saisarvesh6", 1044, 1044, 717, 1059),
    ("gangadhar25", 958, 958, 852, 800),
    ]


# ---------------------------------------------------------
# DATABASE
# ---------------------------------------------------------

def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init():
    c = db()

    c.executescript("""
    CREATE TABLE IF NOT EXISTS players(
        username TEXT PRIMARY KEY,
        rating INTEGER DEFAULT 0,
        rapid INTEGER DEFAULT 0,
        blitz INTEGER DEFAULT 0,
        bullet INTEGER DEFAULT 0,
        games INTEGER DEFAULT 0,
        galactic_points INTEGER DEFAULT 0,
        last_sync TEXT
    );

    CREATE TABLE IF NOT EXISTS games(
        uuid TEXT PRIMARY KEY,
        url TEXT,
        white TEXT,
        black TEXT,
        white_rating INTEGER,
        black_rating INTEGER,
        result TEXT,
        time_class TEXT,
        end_time INTEGER,
        pgn TEXT
    );

    CREATE TABLE IF NOT EXISTS sync_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        started TEXT,
        finished TEXT,
        message TEXT,
        players_synced INTEGER,
        games_synced INTEGER
    );
    """)

    for p in SEED:
        c.execute(
            """
            INSERT OR IGNORE INTO players
            (username, rating, rapid, blitz, bullet)
            VALUES (?, ?, ?, ?, ?)
            """,
            p
        )

    c.commit()
    c.close()


# ---------------------------------------------------------
# CHESS.COM API
# ---------------------------------------------------------

def getj(url):
    r = requests.get(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/json",
            "Accept-Encoding": "gzip"
        },
        timeout=20
    )

    if r.status_code == 429:
        raise RuntimeError(
            "Chess.com API rate limit (429). Try again later."
        )

    if r.status_code != 200:
        raise RuntimeError(
            f"Chess.com API returned {r.status_code}"
        )

    return r.json()


def si(v):
    try:
        return int(v)
    except Exception:
        return 0


# ---------------------------------------------------------
# GET CURRENT CLUB MEMBERS
# ---------------------------------------------------------
def get_current_club_members():
    url = (
        f"https://api.chess.com/pub/club/"
        f"{CLUB_SLUG}/members"
    )

    data = getj(url)

    members = set()

    for group in ("weekly", "monthly", "all_time"):
        for member in data.get(group, []):
            username = member.get("username")

            if username:
                members.add(username)

    if not members:
        raise RuntimeError(
            "Chess.com returned an empty member list. "
            "Database was NOT changed."
        )

    return members
# ---------------------------------------------------------
# RECONCILE DATABASE WITH CHESS.COM CLUB
# ---------------------------------------------------------
def sync_club_members(c):
    current_members = get_current_club_members()

    current_map = {
        username.lower(): username
        for username in current_members
    }

    database_rows = c.execute(
        "SELECT username FROM players"
    ).fetchall()

    database_map = {
        row["username"].lower(): row["username"]
        for row in database_rows
    }

    added = 0
    removed = 0

    # Add new members
    for key, username in current_map.items():
        if key not in database_map:
            c.execute(
                """
                INSERT INTO players(username)
                VALUES(?)
                """,
                (username,)
            )
            added += 1

    # Remove members who left the club
    for key, username in database_map.items():
        if key not in current_map:
            c.execute(
                """
                DELETE FROM players
                WHERE lower(username) = ?
                """,
                (key,)
            )
            removed += 1

    return set(current_map.values()), added, removed
# ---------------------------------------------------------
# PLAYER SYNC
# ---------------------------------------------------------

def sync_player(c, u, months=2):

    p = getj(
        f"https://api.chess.com/pub/player/{u}"
    )

    s = getj(
        f"https://api.chess.com/pub/player/{u}/stats"
    )

    actual_username = p.get("username", u)
    rapid = s.get("chess_rapid", {})
    blitz = s.get("chess_blitz", {})
    bullet = s.get("chess_bullet", {})

    c.execute(
        """
        INSERT INTO players
        (
            username,
            rating,
            rapid,
            blitz,
            bullet,
            last_sync
        )
        VALUES (?, ?, ?, ?, ?, ?)

        ON CONFLICT(username)
        DO UPDATE SET
            rating = excluded.rating,
            rapid = excluded.rapid,
            blitz = excluded.blitz,
            bullet = excluded.bullet,
            last_sync = excluded.last_sync
        """,
        (
            actual_username,

            si(
                p.get("rating")
                or rapid.get("last", {}).get("rating")
            ),

            si(
                rapid.get("last", {}).get("rating")
            ),

            si(
                blitz.get("last", {}).get("rating")
            ),

            si(
                bullet.get("last", {}).get("rating")
            ),

            datetime.now(timezone.utc).isoformat()
        )
    )

    archives = getj(
        f"https://api.chess.com/pub/player/"
        f"{actual_username}/games/archives"
    ).get("archives", [])

    games_count = 0

    for archive in archives[-months:]:

        archive_data = getj(archive)

        for game in archive_data.get("games", []):

            uid = (
                game.get("uuid")
                or game.get("url")
            )

            if not uid:
                continue

            white = game.get("white", {})
            black = game.get("black", {})

            c.execute(
                """
                INSERT OR REPLACE INTO games
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uid,
                    game.get("url", ""),
                    white.get("username", ""),
                    black.get("username", ""),
                    si(white.get("rating")),
                    si(black.get("rating")),
                    (
                        f"{white.get('result', '')} / "
                        f"{black.get('result', '')}"
                    ),
                    game.get("time_class", ""),
                    si(game.get("end_time")),
                    game.get("pgn", "")
                )
            )

            games_count += 1

    c.execute(
        """
        UPDATE players
        SET games = (
            SELECT COUNT(*)
            FROM games
            WHERE
                lower(white) = lower(?)
                OR
                lower(black) = lower(?)
        )
        WHERE lower(username) = lower(?)
        """,
        (
            actual_username,
            actual_username,
            actual_username
        )
    )

    return games_count


# ---------------------------------------------------------
# STARTUP
# ---------------------------------------------------------

def seed():
    init()


# ---------------------------------------------------------
# HOME
# ---------------------------------------------------------

@APP.route("/")
def index():

    c = db()

    players = [
        dict(x)
        for x in c.execute(
            """
            SELECT *
            FROM players
            ORDER BY galactic_points DESC, rating DESC
            """
        )
    ]

    games = [
        dict(x)
        for x in c.execute(
            """
            SELECT *
            FROM games
            ORDER BY end_time DESC
            LIMIT 40
            """
        )
    ]

    c.close()

    return render_template(
        "index.html",
        players=players,
        games=games,
        club_url=CLUB_URL,
        tournament_url=TOURNAMENT_URL
    )


# ---------------------------------------------------------
# STATUS
# ---------------------------------------------------------

@APP.get("/api/status")
def status():

    c = db()

    players = c.execute(
        "SELECT COUNT(*) n FROM players"
    ).fetchone()["n"]

    games = c.execute(
        "SELECT COUNT(*) n FROM games"
    ).fetchone()["n"]

    c.close()

    return jsonify(
        ok=True,
        club="PreMove Legends",
        members=players,
        games=games
    )


# ---------------------------------------------------------
# FULL AUTOMATIC SYNC
# ---------------------------------------------------------

@APP.post("/api/sync")
def sync():

    c = db()

    start = datetime.now(
        timezone.utc
    ).isoformat()

    months = max(
        1,
        min(
            12,
            si(
                (request.json or {}).get(
                    "months",
                    2
                )
            )
        )
    )

    errors = []
    players_synced = 0
    games_synced = 0

    try:

        # ---------------------------------------------
        # STEP 1: GET CURRENT CLUB MEMBERS
        # ---------------------------------------------

        current_members, added, removed = (
            sync_club_members(c)
        )

        c.commit()

        # ---------------------------------------------
        # STEP 2: SYNC EVERY CURRENT MEMBER
        # ---------------------------------------------

        for username in sorted(current_members):

            try:

                games_synced += sync_player(
                    c,
                    username,
                    months
                )

                players_synced += 1

                c.commit()

                time.sleep(0.25)

            except Exception as e:

                errors.append(
                    f"{username}: {e}"
                )

        message = (
            f"Club sync complete. "
            f"{players_synced}/{len(current_members)} "
            f"players synced. "
            f"{added} added, "
            f"{removed} removed, "
            f"{games_synced} games processed."
        )

        if errors:
            message += (
                " Errors: "
                + " ; ".join(errors[:4])
            )

        c.execute(
            """
            INSERT INTO sync_log
            (
                started,
                finished,
                message,
                players_synced,
                games_synced
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                start,
                datetime.now(timezone.utc).isoformat(),
                message,
                players_synced,
                games_synced
            )
        )

        c.commit()

        return jsonify(
            ok=True,
            message=message,
            players_synced=players_synced,
            games_synced=games_synced,
            added=added,
            removed=removed,
            errors=errors
        )

    except Exception as e:

        c.rollback()

        message = (
            f"Club member sync failed: {e}. "
            "Existing database was not reconciled."
        )

        c.execute(
            """
            INSERT INTO sync_log
            (
                started,
                finished,
                message,
                players_synced,
                games_synced
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                start,
                datetime.now(timezone.utc).isoformat(),
                message,
                0,
                0
            )
        )

        c.commit()

        return jsonify(
            ok=False,
            message=message,
            players_synced=0,
            games_synced=0,
            errors=[str(e)]
        ), 500

    finally:

        c.close()


# ---------------------------------------------------------
# LEADERBOARD
# ---------------------------------------------------------

@APP.route("/leaderboard")
def leaderboard():

    c = db()

    players = [
        dict(x)
        for x in c.execute(
            """
            SELECT *
            FROM players
            ORDER BY galactic_points DESC, rating DESC
            """
        )
    ]

    c.close()

    return render_template(
        "leaderboard.html",
        players=players,
        club_url=CLUB_URL,
        tournament_url=TOURNAMENT_URL
    )


# ---------------------------------------------------------
# GAMES
# ---------------------------------------------------------

@APP.route("/games")
def games():

    q = request.args.get(
        "q",
        ""
    ).strip()

    c = db()

    if q:

        rows = c.execute(
            """
            SELECT *
            FROM games
            WHERE
                lower(white) LIKE lower(?)
                OR
                lower(black) LIKE lower(?)
            ORDER BY end_time DESC
            LIMIT 200
            """,
            (
                f"%{q}%",
                f"%{q}%"
            )
        ).fetchall()

    else:

        rows = c.execute(
            """
            SELECT *
            FROM games
            ORDER BY end_time DESC
            LIMIT 200
            """
        ).fetchall()

    c.close()

    return render_template(
        "games.html",
        games=[dict(x) for x in rows],
        q=q,
        club_url=CLUB_URL,
        tournament_url=TOURNAMENT_URL
    )


# ---------------------------------------------------------
# ADMIN
# ---------------------------------------------------------

@APP.route(
    "/admin",
    methods=["GET", "POST"]
)
def admin():

    if request.method == "POST":

        if (
            request.form.get("password")
            == ADMIN_PASSWORD
        ):

            session["admin"] = True

            return redirect(
                url_for("admin")
            )

        return render_template(
            "admin_login.html",
            club_url=CLUB_URL,
            tournament_url=TOURNAMENT_URL,
            error="Wrong password."
        )

    if not session.get("admin"):

        return render_template(
            "admin_login.html",
            club_url=CLUB_URL,
            tournament_url=TOURNAMENT_URL
        )

    c = db()

    players = [
        dict(x)
        for x in c.execute(
            """
            SELECT *
            FROM players
            ORDER BY username
            """
        )
    ]

    c.close()

    return render_template(
        "admin.html",
        players=players,
        club_url=CLUB_URL,
        tournament_url=TOURNAMENT_URL
    )


# ---------------------------------------------------------
# MANUAL ADD
# ---------------------------------------------------------

@APP.post("/admin/add")
def add():

    if not session.get("admin"):
        return redirect(url_for("admin"))

    username = re.sub(
        r"[^A-Za-z0-9_-]",
        "",
        request.form.get(
            "username",
            ""
        )
    ).lower()

    if username:

        c = db()

        c.execute(
            """
            INSERT OR IGNORE INTO players(username)
            VALUES(?)
            """,
            (username,)
        )

        c.commit()
        c.close()

    return redirect(
        url_for("admin")
    )


# ---------------------------------------------------------
# MANUAL REMOVE
# ---------------------------------------------------------

@APP.post("/admin/remove")
def remove():

    if not session.get("admin"):
        return redirect(url_for("admin"))

    username = request.form.get(
        "username",
        ""
    ).lower()

    c = db()

    c.execute(
        """
        DELETE FROM players
        WHERE username = ?
        """,
        (username,)
    )

    c.commit()
    c.close()

    return redirect(
        url_for("admin")
    )


# ---------------------------------------------------------
# LOGOUT
# ---------------------------------------------------------

@APP.get("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("index")
    )


# ---------------------------------------------------------
# START APP
# ---------------------------------------------------------

seed()

if __name__ == "__main__":

    APP.run(
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                5000
            )
        ),
        debug=True
    )
