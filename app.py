from flask import Flask, render_template, request, jsonify, g, redirect
import re
import sqlite3
from flask.helpers import url_for
import requests
from flask_apscheduler import APScheduler
from datetime import datetime
from dotenv import dotenv_values
from mailjet_rest import Client
import hashlib
import itertools

app = Flask(__name__)
config = dotenv_values(".env")
scheduler = APScheduler()


DATABASE = './database.db'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def hash_email(email):
  salt = '1d5205d55'
  return hashlib.sha256(salt.encode() + email.encode()).hexdigest() + ':' + salt

def check_email(hashed_email, given_email):
  email, salt = hashed_email.split(':')
  return email == hashlib.sha256(salt.encode() + given_email.encode()).hexdigest()

def insert_email_to_db(email):
  """funkcja wpisuje mail do bazy danych"""
  print(email)
  sql = 'INSERT OR IGNORE INTO emails(EMAIL) VALUES(?)'
  with get_db() as cursor:
    res = cursor.execute(sql, (email,))
    return res.rowcount

def delete_email_from_db(email):
  """funkcja usuwa mail z bazy danych"""
  sql = 'DELETE FROM emails WHERE email = ?'
  with get_db() as cursor:
    res = cursor.execute(sql, (email,))
    return res.rowcount

def integrity_check(arr1, arr2): #arr1 = db arr2 = api
  """funkcja porownuje wynik z bazy danych do wyniku z api"""
  print(len(arr1))
  print(len(arr2))
  if len(arr2) > len(arr1): #api zwraca wiecej wynikow niz w bazie
    return False

  integrity = True
  iter = 0
  for item in arr1:
    item = ''.join(map(str, item))
    if item != arr2[iter][0]: # roznica bazy z api
      print(item + ' || ' + arr2[iter][0])
      integrity = False 
    iter += 1
  return integrity

def get_all_recipients():
  """funkcja zwraca tablice wszystkich maili osob zapisanych do newslettera"""
  with get_db() as cursor:
    res = cursor.execute('SELECT * FROM emails')
    res = res.fetchall()

    formated_emails = []
    for item in res:
      formated_emails.append({'Email' : item[1]})

    return formated_emails

def get_newest_planet():
  """funkcja zwraca tuple(id, nazwa, planetarium, data_odkrycia)"""
  with get_db() as cursor:
    res = cursor.execute('SELECT * FROM planets LIMIT 1')
    return res.fetchone()

def get_email_body(sandbox = True): 
  """funkcja zwraca json z danymi do wyslania emaila oraz ilosc maili w bazie"""
  planet_info = get_newest_planet()
  recipents = get_all_recipients() # [{'Email':'xxx@xxx.com'},...]
  data = {
    'Messages': [],
  }
  for item in recipents:
    recipent_email = item['Email']
    hashed_email = hash_email(recipent_email)
    data['Messages'].append(
    {
      'FromEmail': 'xionkh123@gmail.com',
      'FromName': 'NasaNotifier',
      'Subject': 'Nasa odkryło nową planete!',
      'Html-part': f'<h3>Nasa właśnie odkryło nową planete o nazwie: {planet_info[1]}!</h3><br />Odkryło ją planetarium o nazwie: {planet_info[2]} w dniu {planet_info[3]}! <br /><br /><br /> <a href="http://127.0.0.1:5000/cancel_newsletter/{hashed_email}">Zrezygnuj z newslettera</a>',
      'Recipients': [{'Email': recipent_email}],
      'SandboxMode': sandbox
    })
  #print(data)
  return [data, len(recipents)] # 0 = body maila 1 = ilosc maili z bazy
  #return data # 0 = body maila 1 = ilosc maili z bazy

def send_emails(): 
  """funkcja wysyla maile i zwraca status, ile maili zostalo wyslanych, ile maili jest w bazie"""
  mailjet = Client(auth=(config['EMAIL_API_KEY'], config['EMAIL_API_SECRET']), version='v3')
  data = get_email_body() # false = wysyla maile nic/true = debugowanie w konsoli 0 = body maila
  result = mailjet.send.create(data=data[0])
  #print(result.status_code)
  return [result.status_code, len(result.json()['Sent']), data[1]] # 0 = kod requestu 1 = ilosc wyslanych maili 2 = ilosc maili z bazy

def update_planets_in_db():
  """funkcja aktualizuje baze danych nowymi planetami z api nasa jesli wystapi niezgodnosc z baza danych"""
  sql_update_planets = 'INSERT OR REPLACE INTO planets(PLANET_NAME, DISC_FACILITY, RELEASE_DATE) VALUES(?, ?, ?)' # query sql do aktualizacji planet
  sql_select_planets = 'SELECT PLANET_NAME FROM planets' # query sql do pobrania nazw planet
  sql_timestamp = 'UPDATE planets_update_timestamp SET TIMESTAMP = ? WHERE ID = 1' # query sql do aktualizacji czasu ostatniej aktualizacji
  print('Pobieranie danych z api NASA')
  # wykonanie zapytania do api nasa w celu pobrania unikalnych nazw planet, planetarium i daty odkrycia w roku 2021 i pozniejszych
  response = requests.get('https://exoplanetarchive.ipac.caltech.edu/TAP/sync?query=select+distinct+pl_name,disc_facility,releasedate+from+ps+where+disc_year+>=+2021+order+by+releasedate+DESC&format=json')
  if(response.status_code == 200): # status 200 czyli zapytanie bylo pomyslne
    print('Pobierano dane z api NASA')
    with app.app_context(): # uzycie kontekstu aplikacji wymagane do dzialania z schedulerem
      print('Aktualizacja planet w bazie danych')

      with get_db() as cursor: # uzycie with powoduje automatyczne zamkniecie kursora po wykonianiu query
        res = cursor.execute(sql_select_planets) # wykonanie query
        res = res.fetchall() # pobranie danych jako tuple
        out = list(itertools.chain(*res)) # zamiana tuple na list potrzebna do integrity_check

        planets_formated = [] # tablica sformatowanych planet z api
        for planet in response.json():
          planets_formated.append((planet["pl_name"], planet["disc_facility"], planet["releasedate"]))
        
        if not integrity_check(out, planets_formated): #brak zgodnosci db z api
          print('Brak zgodnosci aktualizuje planety')
          with get_db() as cursor:
            res = cursor.executemany(sql_update_planets, planets_formated) # aktualizacja planet w bazie danych
            if(res.rowcount > 0):
              print('Zaktualizowano planety')

          print('Wysyłam maile z informacją o nowej planecie')
          email_res = send_emails() # wyslanie maili
          if email_res[0] == 200: # status 200 czyli maile zostaly wyslane pomyslnie
            print(f'Wysłano {email_res[1]} maili do {email_res[2]} odbiorców')
          else:
            print('Błąd przy wysyłaniu maili')

          now = datetime.now() # pobranie aktualnego czasu
          date_time = now.strftime("%m/%d/%Y, %H:%M:%S") # formatowanie czasu do mm/dd/yyyy hh:mm:ss
          with get_db() as cursor:
            res = cursor.execute(sql_timestamp, (date_time,)) # zapisanie czasu statniej aktualizacji w bazie danych
            print('Zaktualizowano timestamp')

def init_db(): # utworzenie bazy z pliku schema.sql
  with app.app_context():
    db = get_db()
    with app.open_resource('schema.sql', mode='r') as f:
        db.cursor().executescript(f.read())
    db.commit()

scheduler.init_app(app) # zainicjalizowanie schedulera
scheduler.add_job(name='update_planets_in_db', id=0, func=update_planets_in_db, trigger='interval', seconds=int(config['PLANETS_REFRESH_RATE'])) # utworzenie nowej pracy schedulera
scheduler.start() # wystartowanie schedulera

@app.route('/')
def index():
  return render_template('index.html')

@app.route('/add_newsletter', methods=['POST'])
def addNewsletter():
  request_json = request.get_json() # {'email': 'xx@xx.xx'}
  regex = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'

  if not (re.match(regex, request_json['email'])): # sprawdzenie czy podany email ma prawidlowy format
    return jsonify({'status': 'invalid_email_format'}) # zwrocenie statusu bledu
  else:
    q = insert_email_to_db(request_json['email']) # proba dodania adresu do bazy
    # zwrot statusow dla toast we front endzie
    if q == 1:
      return jsonify({'status': 'ok'})
    elif q == 0:
      return jsonify({'status': 'email_already_exists'})
    else:
      return jsonify({'status': 'db_error'})

@app.route('/cancel_newsletter/<hashed_email>')
def cancel_newsletter(hashed_email):
  with get_db() as cursor:
    res = cursor.execute('SELECT * FROM emails')
    res = res.fetchall()
    for item in res:
      if check_email(hashed_email, item[1]):
        delete_email_from_db(item[1])
        print(f'znaleziono maila {item[1]}')
  return redirect(url_for('index'), code=302)
