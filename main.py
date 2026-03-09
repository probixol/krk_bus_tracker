# najgorzej zaprojektowany kod nagroda:
# a i tramwaje nie sa supportowane ups xd lol trol


try: # protobuf check
    import requests
    from google.transit import gtfs_realtime_pb2
except ModuleNotFoundError as e:
    print("brak protobufa, uruchom:")
    print("pip install -r requirements.txt")
    input()
    exit(1)

import time as time_module
import requests, csv, zipfile, math, os, io
import shutil, PyQt6, sys
import threading
import socket, sqlite3
import firebase_admin
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import QApplication, QWidget, QGridLayout, QLabel
from PyQt6.QtGui import QFontDatabase, QFont
from firebase_admin import credentials
from firebase_admin import db
from google.transit import gtfs_realtime_pb2
from datetime import datetime, timedelta
from pathlib import Path
now = datetime.now()
time = timedelta(hours=now.hour, minutes=now.minute, seconds=now.second)
time_nosec = timedelta(hours=now.hour, minutes=now.minute)
today = datetime.weekday(datetime.now())
found = False
headers = {
    "User-Agent": "Mozilla/5.0"
}
live = 0
p = 0
x = 0
y = 0
z = 0
upcoming_trips = []
ignore_bus = []
stop_list = []
trip_ids = []
stop_ids = []
stop_lat = []
stop_lon = []
kml_stop_ids = {}
czas = []
linia = []
kierunek = []
na_zywo = []
rozklad = {}
czas_dict = {}
linia_dict = {}
stops_data = {}
kierunek_dict = {}
na_zywo_dict = {}
block_to_route = {} # slownik blockow na routy
block_to_dest = {}
block_to_direction = {}
block_to_service = {}
route_to_number = {}  # slownik routow na number linii
socket.setdefaulttimeout(10)
# uniwersalne foldery
PROJECT_DIR = Path(__file__).resolve().parent  # glowny folder
GTFS_KRK_A = PROJECT_DIR / "GTFS_KRK_A"
GTFS_KRK_M = PROJECT_DIR / "GTFS_KRK_M"
GTFS_KML = PROJECT_DIR / "ald-gtfs"
config = PROJECT_DIR / "CONFIG.txt"

# ta czesc kodu od googla
KEY_PATH = PROJECT_DIR / "krk-bus-tracker-firebase-adminsdk-fbsvc-0b46cc464b.json"
DATABASE_URL = 'https://krk-bus-tracker-default-rtdb.europe-west1.firebasedatabase.app'
try:
    if not os.path.exists(KEY_PATH): # klucz check
        raise FileNotFoundError(f"Nie znalzeiono klucza pod adresem: {KEY_PATH}")
    cred = credentials.Certificate(KEY_PATH)
    firebase_admin.initialize_app(cred, {
        'databaseURL': DATABASE_URL
    })
    print("Firebase database dziala!")
except FileNotFoundError as e:
    print(f"Error: {e}")
    print("Prawdopodobnie problem z KEY_PATH")
    exit()
except ValueError as e:
    print(f"Error initializing Firebase: {e}")
    print("Sprawdz SERVICE_ACCOUNT_KEY_PATH i DATABASE_URL.")
    exit()
except Exception as e:
    print(f"Blad typu exception: {e}")
    exit()

database_dir = db.reference()
print(f"Connected to database at: {DATABASE_URL}")

czas_dir = db.reference("00/czas")
linia_dir = db.reference("00/linia")
kierunek_dir = db.reference("00/kierunek")
live_dir = db.reference("00/live")
przystanek_dir = database_dir.child('przystanek')
czasczas_dir = database_dir.child('czasczas')


def update_db(base_dir, db_path):
    print(f"Indeksowanie bazy dla {base_dir.name}... (to chwilę potrwa)")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    # tworzenie tabeli
    cursor.execute("DROP TABLE IF EXISTS stop_times")
    cursor.execute("CREATE TABLE stop_times (trip_id TEXT, arrival_time TEXT, stop_id TEXT)")

    stop_times_txt = base_dir / "stop_times.txt"
    with stop_times_txt.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        # Wczytujemy dane partiami, żeby nie zapchać RAMu
        to_db = [(r['trip_id'], r['arrival_time'], r['stop_id']) for r in reader]
        cursor.executemany("INSERT INTO stop_times VALUES (?, ?, ?);", to_db)

    # indeks jest szybszy
    cursor.execute("CREATE INDEX idx_stop ON stop_times(stop_id)")
    conn.commit()
    conn.close()
    print("Indeksowanie zakończone!")

def internet_available():
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=5)
        return True
    except OSError:
        return False

def timetable_update():
    today_str = datetime.now().strftime("%Y-%m-%d")
    data = PROJECT_DIR / "DATA.txt"

    if data.exists():
        with data.open("r", encoding="utf-8") as f:
            last_update = f.read().strip()
    else:
        last_update = None
    if last_update != today_str:
        internet = internet_available()
        if internet == True:
            print("Aktualizacja GTFS. . .")
            urls_and_dirs = [
                ("https://gtfs.ztp.krakow.pl/GTFS_KRK_A.zip", GTFS_KRK_A),
                ("https://gtfs.ztp.krakow.pl/GTFS_KRK_M.zip", GTFS_KRK_M),
                ("https://www.kolejemalopolskie.com.pl/rozklady_jazdy/ald-gtfs.zip", GTFS_KML)
            ]
            for url, folder in urls_and_dirs:
                try:
                    response = requests.get(url, headers=headers, timeout=30)
                    response.raise_for_status()
                    zip_file = zipfile.ZipFile(io.BytesIO(response.content))
                    zip_file.extractall(folder)
                    print(f"Pobrano i wypakowano: {url}")
                except Exception as e:
                    print("GTFS update failed:", e)

            with data.open("w", encoding="utf-8") as f:
                f.write(today_str)

def translator(base_dir):
    trips = base_dir / "trips.txt"
    with trips.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            block_to_route[row["trip_id"]] = row["route_id"]
            block_to_dest[row["trip_id"]] = row["trip_headsign"]
            block_to_service[row["trip_id"]] = row["service_id"]
            if base_dir != GTFS_KML:
                block_to_direction[row["trip_id"]] = row["direction_id"]
    routes = base_dir / "routes.txt"
    with routes.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            route_to_number[row["route_id"]] = row["route_short_name"]


PROJECT_DIR = Path(__file__).resolve().parent # ogolny folder
GTFS_DIRS = [ # foldery poszczegolnych gtfs
    PROJECT_DIR / "GTFS_KRK_A",
    PROJECT_DIR / "GTFS_KRK_M",
    PROJECT_DIR / "ald-gtfs",
]
base_dir = GTFS_KRK_A
routes = base_dir / "routes.txt"
trips = base_dir / "trips.txt"
trip_updates = base_dir / "trip_updates.txt"

def parse_gtfs_time(time_str):
    h, m, s = map(int, time_str.split(":"))
    return timedelta(hours=h, minutes=m, seconds=s)

def refresh_time(): # poniewaz czas sie pieprzy po sleepach
    global now, time, time_nosec, today
    now = datetime.now()
    time = timedelta(hours=now.hour, minutes=now.minute, seconds=now.second)
    time_nosec = timedelta(hours=now.hour, minutes=now.minute)
    today = datetime.weekday(now)
    czasczas = str(time_nosec)
    czasczas = czasczas[:-3]
    print(czasczas)
    czasczas_dir.set(czasczas)

def stop_find(base_dir):
    stops = base_dir / "stops.txt"
    y = 0
    found = False
    with stops.open(newline="", encoding="utf-8-sig") as f: # lista wybranych przystankow KRK!!!
        reader = csv.DictReader(f)
        for row in reader:
            if row["stop_name"] == stop:
                if row.get("stop_desc") in (None, ""):
                    try:
                        loc_type = int(row.get("location_type", ""))
                    except ValueError:
                        loc_type = None
                    if direction.isdigit() and loc_type is not None and loc_type == int(direction):
                        stop_ids.append(row["stop_id"])
                if row.get("stop_desc") == direction:
                    stop_lat.append(float(row["stop_lat"]))
                    stop_lon.append(float(row["stop_lon"]))
                    stop_ids.append(row["stop_id"])
                    found = True
                    print("Przystanek KRK >> " + row["stop_id"])
                    print(stop_lon)
                    print(stop_lat)
                    break
                if direction == "00":
                    stop_lat.append(float(row["stop_lat"]))
                    stop_lon.append(float(row["stop_lon"]))
                    stop_ids.append(row["stop_id"])
                    found = True
                    print("Przystanek KRK >> " + row["stop_id"] + " >> " + row["stop_desc"])
                    y = y + 1

def online(URL):
    internet = internet_available()
    if internet == True:
        feed = gtfs_realtime_pb2.FeedMessage()
        try:
            response = requests.get(URL, headers=headers, timeout=10)
            response.raise_for_status()
        except requests.exceptions.ConnectionError:
            print("Brak internetu")
            return
        except requests.exceptions.Timeout:
            print("Timeout")
            return
        except requests.exceptions.HTTPError as e:
            print("Brawo krakow:", e)
            raise
        try:
            feed.ParseFromString(response.content)
        except Exception as e:
            print(f"Blad parsowania protobufa: {e}")
            return

        for entity in feed.entity:
            if entity.HasField("trip_update"): # czy wogole jest kurs, jesli nie ma to kod pozniej nie zadziala
                trip_update = entity.trip_update
                for stop_update in trip_update.stop_time_update:
                    if stop_update.stop_id in stop_ids:
                        if stop_update.HasField("departure") and stop_update.departure.HasField("time"): # sprawdzenie departure
                            unix_time = stop_update.departure.time
                        elif stop_update.HasField("arrival") and stop_update.arrival.HasField("time"): # fallback
                            unix_time = stop_update.arrival.time
                        else:
                            continue
                        departure_dt = datetime.fromtimestamp(unix_time)  # czas odjazdu
                        time_delta = departure_dt - datetime.now()  # timedelta do odjazdu
                        if time_delta.total_seconds() < 0: # jesli odjazd po polnocy
                            time_delta += timedelta(days=1)
                        trip_id = trip_update.trip.trip_id
                        route_id = block_to_route.get(trip_id)
                        line_number = route_to_number.get(route_id) if route_id else None
                        dest = block_to_dest.get(trip_id) if trip_id else None
                        ignore_bus.append(trip_id)
                        departure_td = timedelta(
                            hours=departure_dt.hour,
                            minutes=departure_dt.minute,
                            seconds=departure_dt.second
                        )
                        minutes = int(time_delta.total_seconds() // 60)
                        if minutes <= 0:
                            minutes_str = "0 min"
                        else:
                            minutes_str = f"{minutes} min"
                        if minutes_str == "1439 min":
                            minutes_str = "0 min"
                        live = 1
                        tstop = stop_update.stop_id
                        delay_seconds = stop_update.departure.delay
                        delay_minutes = delay_seconds // 60
                        if delay_minutes > 5:
                            live = 2

                        upcoming_trips.append((departure_td, minutes_str, line_number, dest, trip_id, live, tstop, delay_minutes))

def offline(preloaded, system):
    active_stop_ids = stop_ids if system == "krk" else kml_stop_ids
    if not active_stop_ids:
        return
    for row in preloaded:
        week_to_krk = {0: 1, 1: 1, 2: 1, 3: 5, 4: 4, 5: 2, 6: 3} # pilka zmylka
        week_to_krk_str = {"PO": 1, "CZ": 5, "PT": 4, "SO": 2, "SW": 3}
        week_to_kml = {0: 7952, 1: 7952, 2: 7952, 3: 7952, 4: 7952, 5: 7953, 6: 7954} # serdeczne gratulacje kml
        delay_minutes = 0
        if system == "krk":
            if time < timedelta(hours=3):
                yesterday_check = (week_to_krk[today], week_to_krk[(today - 1) % 7])
            else:
                yesterday_check = (week_to_krk[today],) # nawiasy zeby byla tupla (lista) a nie int
        if system == "kml":
            if time < timedelta(hours=3):
                yesterday_check = (week_to_kml[today], week_to_kml[(today - 1) % 7])
            else:
                yesterday_check = (week_to_kml[today],)
        if row["trip_id"] not in ignore_bus:
            if row["stop_id"] in active_stop_ids:
                tstop = row["stop_id"]
                arrival_td = parse_gtfs_time(row["arrival_time"])  # czas przyjazdu w timedelta
                tommorow_status = arrival_td >= timedelta(hours=24)
                if tommorow_status:  # jesli kurs jest po polnocy to -24h i poprzedni dzien
                    arrival_td = arrival_td - timedelta(hours=24)
                    service_day = (today - 1) % 7
                if arrival_td >= time_nosec:
                    trip_id = row["trip_id"]
                    service_id = block_to_service.get(trip_id, "")
                    week_number = (service_id.split("_")[-1]) if service_id else (trip_id.split("_")[-1])
                    if week_number.isdigit():
                        week_number = int(week_number)
                    else:
                        week_number = week_to_krk_str[week_number]
                    if week_number in yesterday_check:
                        time_diff = arrival_td - time_nosec
                        route_id = block_to_route.get(trip_id)
                        line_number = route_to_number.get(route_id) if route_id else None
                        dest = block_to_dest.get(trip_id) if trip_id else None
                        live = 0
                        if time_diff < timedelta(hours=1):
                            minutes = int(time_diff.total_seconds() // 60)
                            if minutes <= 0:
                                minutes_str = "0 min"
                            else:
                                minutes_str = f"{minutes} min"
                            if minutes_str == "1439 min":
                                minutes_str = "0 min"
                            upcoming_trips.append((arrival_td, minutes_str, line_number, dest, trip_id, live, tstop, delay_minutes))
                            #ignore_bus.append(trip_id)
                        else:
                            h, m, s = map(int, row["arrival_time"].split(":"))
                            dep_time = timedelta(hours=h, minutes=m, seconds=s)
                            if dep_time > timedelta(hours=24):
                                dep_time = dep_time - timedelta(hours=24)
                            dep_time_str = f"{int(dep_time.total_seconds() // 3600):02d}:" \
                                           f"{int((dep_time.total_seconds() % 3600) // 60):02d}"
                            upcoming_trips.append((arrival_td, dep_time_str, line_number, dest, trip_id, live, tstop, delay_minutes))
                            #ignore_bus.append(trip_id)


def preload_stop_times(base_dir, system):
    db_path = base_dir / "data.db"

    # Jeśli baza nie istnieje (np. po aktualizacji ZIP), stwórz ją
    if not db_path.exists():
        update_db(base_dir, db_path)

    active_stop_ids = stop_ids if system == "krk" else list(kml_stop_ids.keys())
    relevant = []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # Dzięki temu wynik działa jak słownik row["stop_id"]
    cursor = conn.cursor()

    # Wyciągamy tylko te rzędy, które pasują do Twoich przystanków
    for s_id in active_stop_ids:
        cursor.execute("SELECT * FROM stop_times WHERE stop_id=?", (s_id,))
        relevant.extend([dict(row) for row in cursor.fetchall()])

    conn.close()
    return relevant

def display(data):
    while len(data['czas']) < ilosc\
            :
        data['czas'].append("")
        data['linia'].append("")
        data['kierunek'].append("")
        data['na_zywo'].append(0)
    while layout.count(): # reset
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
    layout.setColumnStretch(0, 1)
    layout.setColumnStretch(1, 20)
    layout.setColumnStretch(2, 1)
    now = datetime.now()
    czasczas = f"{now.hour:02d}:{now.minute:02d}"
    newdata = []
    busx = 0
    while busx < ilosc:
        if len(data['kierunek'][busx]) >= 19:
            data['kierunek'][busx] = data['kierunek'][busx][:18] + "."
        busx += 1
    busx = 0
    while busx < ilosc:
        newdata.append([
            data['linia'][busx],
            data['kierunek'][busx],
            data['czas'][busx],
            data['na_zywo'][busx]
        ])
        busx += 1
    print(newdata)
    header_label = QLabel(czasczas)
    header_label.setFont(custom_font)
    header_label.setStyleSheet("color: white;")
    layout.addWidget(header_label, 0, 0)

    for row, row_newdata in enumerate(newdata, start=1):
        for col, text in enumerate(row_newdata[:-1]):
            stop_label = QLabel(text)
            stop_label.setFont(custom_font)
            if row_newdata[-1] == 1: # ostatni element w rzedzie
                stop_label.setStyleSheet("color: #32CD32;")  # change text color
            elif row_newdata[-1] == 2: # ostatni element w rzedzie
                stop_label.setStyleSheet("color: #DB143A;")  # change text color
            else:
                stop_label.setStyleSheet("color: white;")
            layout.addWidget(stop_label, row, col)
    window.setStyleSheet("background-color: black;")

with config.open(newline="", encoding="utf-8-sig") as config:
    stop = config.readline().strip()
    direction = config.readline().strip()
    kml = config.readline().strip()
    czcionka = config.readline().strip()
    ilosc = config.readline().strip()
    print("Przystanek: " + str(stop))
    print("Numer przystanka: " + str(direction))
    print("Status KML: " + str(kml))
    print("Czcionka: " + str(czcionka))
    print("Ilosc: " + str(ilosc))
    ilosc = int(ilosc)

przystanek = str(stop + ", " + direction)
przystanek_dir.set(przystanek)

translator(GTFS_KRK_A)
translator(GTFS_KRK_M)
translator(GTFS_KML)
stop_find(GTFS_KRK_A)
stop_find(GTFS_KRK_M)
krk_count = len(stop_ids)
print("Liczba przystankow KRK: " + str(krk_count))
current_stop = 0

# mmmm kocham kiedy przystanki mozna tylko wyjac z ich lokalizacji mmmmm
base_dir = GTFS_KML
kml_stops = base_dir / "stops.txt"
potentials = []
while current_stop < krk_count:
    if stop_lat and stop_lon:
        with kml_stops.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # wzor na odleglosc dwoch punktow SHOUTOUT DLA PIEKARSKIEJ
                current_lat = float(row["stop_lat"])
                current_lon = float(row["stop_lon"])
                distance = math.sqrt(
                    (current_lat - stop_lat[current_stop]) ** 2 + (current_lon - stop_lon[current_stop]) ** 2)
                potentials.append((distance, row["stop_id"]))
            potentials.sort(key=lambda x: x[0])
            kml_stop_ids[potentials[0][1]] = stop_ids[current_stop]
            print("Przystanek KML >> " + str(potentials[0][1]))
            potentials.clear()
            current_stop += 1
print("stop_ids:", stop_ids)
print("stop_lat:", stop_lat)
print("stop_lon:", stop_lon)
print("kml_stop_ids:",kml_stop_ids)
app = QApplication(sys.argv)
app.setOverrideCursor(Qt.CursorShape.BlankCursor)
window = QWidget()
layout = QGridLayout()
window.setLayout(layout)
window.setStyleSheet("background-color: black;")
window.move(0, 0)
window.showFullScreen()

clearview = PROJECT_DIR / "Clearview Font.ttf"
helvetica = PROJECT_DIR / "Helvetica.ttf"
helvetica_bold = PROJECT_DIR / "Helvetica-Bold.ttf"

print(helvetica_bold)
print(helvetica_bold.exists())

if czcionka == "1":
    font_id = QFontDatabase.addApplicationFont(str(clearview))
elif czcionka == "2":
    font_id = QFontDatabase.addApplicationFont(str(helvetica))
else:
    font_id = QFontDatabase.addApplicationFont(str(helvetica_bold))
if font_id == -1:
    print("Failed to load font")
    sys.exit()
font_family = QFontDatabase.applicationFontFamilies(font_id)[0]
custom_font = QFont(font_family, 91)

preloaded_krk_a = preload_stop_times(GTFS_KRK_A, "krk")
preloaded_krk_m = preload_stop_times(GTFS_KRK_M, "krk")
preloaded_kml = preload_stop_times(GTFS_KML, "kml") if kml == "1" else []

def main():
    global run
    global upcoming_trips
    refresh_time()
    upcoming_trips.clear()
    ignore_bus.clear()
    czas.clear()
    linia.clear()
    kierunek.clear()
    na_zywo.clear()
    internet = internet_available()
    print("Internet: " + str(internet))
    # tak moglem to zapisac jakos lepiej i nie, nie chce mi sie
    try:
        online(URL="https://gtfs.ztp.krakow.pl/TripUpdates_A.pb")
        online(URL="https://gtfs.ztp.krakow.pl/TripUpdates_M.pb")
    except requests.exceptions.RequestException as e:
        if internet == False:
            print("Brak intenetu. . .")
        else:
            print(str(time) + " >> last update")
            print("Error: ", e)
            print("Brawo Kraków ! ! !")
    offline(preloaded_krk_a, "krk")
    offline(preloaded_krk_m, "krk")
    if kml == "1":
        offline(preloaded_kml, "kml")
    stops_data.clear()
    print(str(time) + " >> Last update")

    all_data = {"czas": [], "linia": [], "kierunek": [], "na_zywo": []}

    upcoming_trips.sort(key=lambda x: x[0])
    seen = set() # kml wylew bugfix
    deduped = []
    for trip in upcoming_trips:
        key = (trip[0], trip[2], trip[6])  # (czas, linia, tstop)
        if key not in seen:
            seen.add(key)
            deduped.append(trip)
    upcoming_trips = deduped

    for _, arrival_str, line, dest, trip_id, live, tstop, delay_minutes in upcoming_trips:
        line = line or "??"  # fallback gdyby nie bylo
        dest = dest or "??"
        tstop = kml_stop_ids.get(tstop, tstop)
        tstop = tstop[-2:]
        #print(f"{arrival_str} >> {line} >> {dest} >> {status} >> {trip_id} >> {tstop}")
        if tstop not in stops_data:
            stops_data[tstop] = {"czas": [], "linia": [], "kierunek": [], "na_zywo": []} #
        if len(stops_data[tstop]["czas"]) < ilosc:
            stops_data[tstop]["czas"].append(arrival_str) # sortowanie danych do odpowienich katergorii
            stops_data[tstop]["linia"].append(line)
            stops_data[tstop]["kierunek"].append(dest)
            stops_data[tstop]["na_zywo"].append(live)
            if direction == tstop:
                print(f"{arrival_str} >> {line} >> {dest} >> {live} >> {tstop} >> {trip_id}")
            if len(all_data["czas"]) < ilosc:
                all_data["czas"].append(arrival_str)  # 00
                all_data["linia"].append(line)
                all_data["kierunek"].append(dest)
                all_data["na_zywo"].append(live)
                print(f"{arrival_str} >> {line} >> {dest} >> {live} >> {tstop} >> {trip_id}")

    print(ignore_bus)
    try:
        db.reference("00").set(all_data) # zapisanie 00
        root_ref = db.reference()
        for stop_id, data in stops_data.items(): # tworzenie folderow 00 01 itp
            root_ref.child(stop_id).set(data) # np. w 01 daje wszystko
    except Exception as e:
        print("Firebase offline:", e)
    display(all_data)
    return True

threading.Thread(target=timetable_update, daemon=True).start()
main()
timer = QTimer()
timer.timeout.connect(main)
timer.start(20000)

sys.exit(app.exec())
