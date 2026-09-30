import os,re,sqlite3,time
from datetime import datetime,timezone
from flask import Flask,render_template,jsonify,request,redirect,url_for,session
import requests
APP=Flask(__name__); APP.secret_key=os.environ.get('SECRET_KEY','change-this-secret-key'); DB=os.environ.get('DATABASE_PATH','premove_legends.db')
CLUB_URL=os.environ.get('CLUB_URL','https://link.chess.com/club/W6nZgx'); TOURNAMENT_URL=os.environ.get('TOURNAMENT_URL','https://www.chess.com/play/arena/31104118'); ADMIN_PASSWORD=os.environ.get('ADMIN_PASSWORD','legend123')
SEED=[('blinking_blunders',2117,2117,2574,2567),('sriwarior',1992,1992,1743,1606),('positionwizards',1920,1920,1912,0),('premove-legends',1704,1704,1372,0),('harrypotterkaelenaetheris',1640,1640,1506,1266),('phantomvertex',1160,1160,994,1055),('shuttleblitz',1105,1105,897,809),('saisarvesh6',1044,1044,717,1059),('gangadhar25',958,958,852,800)]
UA=os.environ.get('CHESS_API_USER_AGENT','PremoveLegendsDashboard/1.0 (contact: replace-with-your-email@example.com)')
def db():
 c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
def init():
 c=db(); c.executescript('''CREATE TABLE IF NOT EXISTS players(username TEXT PRIMARY KEY,rating INTEGER DEFAULT 0,rapid INTEGER DEFAULT 0,blitz INTEGER DEFAULT 0,bullet INTEGER DEFAULT 0,games INTEGER DEFAULT 0,galactic_points INTEGER DEFAULT 0,last_sync TEXT); CREATE TABLE IF NOT EXISTS games(uuid TEXT PRIMARY KEY,url TEXT,white TEXT,black TEXT,white_rating INTEGER,black_rating INTEGER,result TEXT,time_class TEXT,end_time INTEGER,pgn TEXT); CREATE TABLE IF NOT EXISTS sync_log(id INTEGER PRIMARY KEY AUTOINCREMENT,started TEXT,finished TEXT,message TEXT,players_synced INTEGER,games_synced INTEGER);''')
 for p in SEED:c.execute('INSERT OR IGNORE INTO players(username,rating,rapid,blitz,bullet) VALUES(?,?,?,?,?)',p)
 c.commit();c.close()
def getj(url):
 r=requests.get(url,headers={'User-Agent':UA,'Accept':'application/json','Accept-Encoding':'gzip'},timeout=20)
 if r.status_code==429: raise RuntimeError('Chess.com API rate limit (429). Try again later.')
 if r.status_code!=200: raise RuntimeError(f'Chess.com API returned {r.status_code}')
 return r.json()
def si(v):
 try:return int(v)
 except:return 0
def sync_player(c,u,months=2):
 p=getj(f'https://api.chess.com/pub/player/{u}'); s=getj(f'https://api.chess.com/pub/player/{u}/stats'); a=p.get('username',u).lower(); q=s.get('chess_rapid',{}); b=s.get('chess_blitz',{}); bu=s.get('chess_bullet',{})
 c.execute('''INSERT INTO players(username,rating,rapid,blitz,bullet,last_sync) VALUES(?,?,?,?,?,?) ON CONFLICT(username) DO UPDATE SET rating=excluded.rating,rapid=excluded.rapid,blitz=excluded.blitz,bullet=excluded.bullet,last_sync=excluded.last_sync''',(a,si(p.get('rating') or q.get('last',{}).get('rating')),si(q.get('last',{}).get('rating')),si(b.get('last',{}).get('rating')),si(bu.get('last',{}).get('rating')),datetime.now(timezone.utc).isoformat()))
 archives=getj(f'https://api.chess.com/pub/player/{a}/games/archives').get('archives',[]); n=0
 for ar in archives[-months:]:
  for g in getj(ar).get('games',[]):
   uid=g.get('uuid') or g.get('url'); w=g.get('white',{}); bl=g.get('black',{})
   if not uid:continue
   c.execute('INSERT OR REPLACE INTO games VALUES(?,?,?,?,?,?,?,?,?,?)',(uid,g.get('url',''),w.get('username',''),bl.get('username',''),si(w.get('rating')),si(bl.get('rating')),f"{w.get('result','')} / {bl.get('result','')}",g.get('time_class',''),si(g.get('end_time')),g.get('pgn',''))); n+=1
 c.execute('UPDATE players SET games=(SELECT COUNT(*) FROM games WHERE lower(white)=lower(?) OR lower(black)=lower(?)) WHERE lower(username)=lower(?)',(a,a,a));return n
def seed():init()
@APP.route('/')
def index():
 c=db(); ps=[dict(x) for x in c.execute('SELECT * FROM players ORDER BY galactic_points DESC,rating DESC')]; gs=[dict(x) for x in c.execute('SELECT * FROM games ORDER BY end_time DESC LIMIT 40')]; c.close(); return render_template('index.html',players=ps,games=gs,club_url=CLUB_URL,tournament_url=TOURNAMENT_URL)
@APP.get('/api/status')
def status():
 c=db(); a=c.execute('SELECT COUNT(*) n FROM players').fetchone()['n']; g=c.execute('SELECT COUNT(*) n FROM games').fetchone()['n']; c.close(); return jsonify(ok=True,club='PreMove Legends',members=a,games=g)
@APP.post('/api/sync')
def sync():
 c=db(); start=datetime.now(timezone.utc).isoformat(); users=[x['username'] for x in c.execute('SELECT username FROM players')]; months=max(1,min(12,si((request.json or {}).get('months',2)))); ok=n=0; errs=[]
 for u in users:
  try:n+=sync_player(c,u,months);ok+=1;c.commit();time.sleep(.25)
  except Exception as e:errs.append(f'{u}: {e}')
 msg=f'Synced {ok}/{len(users)} players and processed {n} games.'+(' | '+' ; '.join(errs[:4]) if errs else '')
 c.execute('INSERT INTO sync_log(started,finished,message,players_synced,games_synced) VALUES(?,?,?,?,?)',(start,datetime.now(timezone.utc).isoformat(),msg,ok,n));c.commit();c.close();return jsonify(ok=ok>0,message=msg,players_synced=ok,games_synced=n,errors=errs)
@APP.route('/leaderboard')
def leaderboard():
 c=db();p=[dict(x) for x in c.execute('SELECT * FROM players ORDER BY galactic_points DESC,rating DESC')];c.close();return render_template('leaderboard.html',players=p,club_url=CLUB_URL,tournament_url=TOURNAMENT_URL)
@APP.route('/games')
def games():
 q=request.args.get('q','').strip();c=db();
 if q:r=c.execute('SELECT * FROM games WHERE lower(white) LIKE lower(?) OR lower(black) LIKE lower(?) ORDER BY end_time DESC LIMIT 200',(f'%{q}%',f'%{q}%')).fetchall()
 else:r=c.execute('SELECT * FROM games ORDER BY end_time DESC LIMIT 200').fetchall()
 c.close();return render_template('games.html',games=[dict(x) for x in r],q=q,club_url=CLUB_URL,tournament_url=TOURNAMENT_URL)
@APP.route('/admin',methods=['GET','POST'])
def admin():
 if request.method=='POST':
  if request.form.get('password')==ADMIN_PASSWORD:session['admin']=True;return redirect(url_for('admin'))
  return render_template('admin_login.html',club_url=CLUB_URL,tournament_url=TOURNAMENT_URL,error='Wrong password.')
 if not session.get('admin'):return render_template('admin_login.html',club_url=CLUB_URL,tournament_url=TOURNAMENT_URL)
 c=db();p=[dict(x) for x in c.execute('SELECT * FROM players ORDER BY username')];c.close();return render_template('admin.html',players=p,club_url=CLUB_URL,tournament_url=TOURNAMENT_URL)
@APP.post('/admin/add')
def add():
 if not session.get('admin'):return redirect(url_for('admin'))
 u=re.sub(r'[^A-Za-z0-9_-]','',request.form.get('username','')).lower();c=db();c.execute('INSERT OR IGNORE INTO players(username) VALUES(?)',(u,));c.commit();c.close();return redirect(url_for('admin'))
@APP.post('/admin/remove')
def remove():
 if not session.get('admin'):return redirect(url_for('admin'))
 c=db();c.execute('DELETE FROM players WHERE username=?',(request.form.get('username','').lower(),));c.commit();c.close();return redirect(url_for('admin'))
@APP.get('/logout')
def logout():session.clear();return redirect(url_for('index'))
seed()
if __name__=='__main__':APP.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)),debug=True)
