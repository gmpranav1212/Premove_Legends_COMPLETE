PREMOVE LEGENDS COMPLETE WEBSITE

Includes Flask + SQLite + public Chess.com player/game sync + leaderboard + searchable games + staff member management + galactic UI.

LOCAL:
1. Open Command Prompt in this folder.
2. Run start.bat
3. Open http://127.0.0.1:5000

Default staff password: legend123

RENDER:
Build: pip install -r requirements.txt
Start: gunicorn app:APP --bind 0.0.0.0:$PORT
For persistent SQLite data on a host, use persistent storage or PostgreSQL.

Set these environment variables for deployment:
ADMIN_PASSWORD=your-password
SECRET_KEY=long-random-secret
CHESS_API_USER_AGENT=PremoveLegendsDashboard/1.0 (contact: your-email@example.com)

Chess.com PubAPI is read-only. It can provide public data but cannot modify club membership.
The dashboard syncs the latest 2 monthly player game archives per member by default.
