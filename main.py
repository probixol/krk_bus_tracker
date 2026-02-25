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

import firebase_admin
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

def timetable_update():
    today_str = datetime.now().strftime("%Y-%m-%d")
    data = PROJECT_DIR / "DATA.txt"

    if data.exists():
        with data.open("r", encoding="utf-8") as f:
            last_update = f.read().strip()
    else:
        last_update = None
    if last_update != today_str:
        print("Aktualizacja GTFS. . .")
        urls_and_dirs = [
            ("https://gtfs.ztp.krakow.pl/GTFS_KRK_A.zip", GTFS_KRK_A),
            ("https://gtfs.ztp.krakow.pl/GTFS_KRK_M.zip", GTFS_KRK_M),
            ("https://www.kolejemalopolskie.com.pl/rozklady_jazdy/ald-gtfs.zip", GTFS_KML)
        ]
        for url, folder in urls_and_dirs:
            response = requests.get(url, headers=headers, timeout=10)
            zip_file = zipfile.ZipFile(io.BytesIO(response.content))
            zip_file.extractall(folder)
            print(f"Pobrano i wypakowano: {url}")

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
    response = requests.get(URL, headers=headers, timeout=10)
    feed = gtfs_realtime_pb2.FeedMessage()
    if not response.content:
        print("Error 1 (brawo krakow)")
        return
    try: # anti crash
        feed.ParseFromString(response.content)
    except Exception as e:
        print(f"Error 2 (brawo krakow): {e}")
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
                    minutes = f"{minutes} min"
                    if minutes == "1439 min" or minutes == "0 min":
                        minutes = "DEPARTING"
                    live = True
                    tstop = stop_update.stop_id
                    upcoming_trips.append((departure_td, minutes, line_number, dest, trip_id, live, tstop))

def offline(base_dir, system):
    stop_times = base_dir / "stop_times.txt"
    active_stop_ids = stop_ids if system == "krk" else kml_stop_ids
    if not active_stop_ids:
        return
    with stop_times.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader: # dlaczego jest to niepotrzebnie zkomplikowane ?  ??  ?
            week_to_krk = {0: 1, 1: 1, 2: 1, 3: 5, 4: 4, 5: 2, 6: 3} # pilka zmylka
            week_to_krk_str = {"PO": 1, "CZ": 5, "PT": 4, "SO": 2, "SW": 3}
            week_to_kml = {0: 7952, 1: 7952, 2: 7952, 3: 7952, 4: 7952, 5: 7953, 6: 7954} # serdeczne gratulacje kml
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
                            live = False
                            if time_diff < timedelta(hours=1):
                                minutes = int(time_diff.total_seconds() // 60)
                                minutes_str = f"{minutes} min"
                                if minutes_str == "1439 min" or minutes_str == "0 min":
                                    minutes_str = "DEPARTING"
                                upcoming_trips.append((arrival_td, minutes_str, line_number, dest, trip_id, live, tstop))
                            else:
                                h, m, s = map(int, row["arrival_time"].split(":"))
                                dep_time = timedelta(hours=h, minutes=m, seconds=s)
                                if dep_time > timedelta(hours=24):
                                    dep_time = dep_time - timedelta(hours=24)
                                dep_time_str = f"{int(dep_time.total_seconds() // 3600):02d}:" \
                                               f"{int((dep_time.total_seconds() % 3600) // 60):02d}"
                                upcoming_trips.append((arrival_td, dep_time_str, line_number, dest, trip_id, live, tstop))


with config.open(newline="", encoding="utf-8-sig") as config:
    stop = config.readline().strip()
    direction = config.readline().strip()
    kml = config.readline().strip()
    print("Przystanek: " + str(stop))
    print("Numer przystanka: " + str(direction))
    print("Status KML: " + str(kml))

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

def main():
    timetable_update()
    refresh_time()
    upcoming_trips.clear()
    ignore_bus.clear()
    czas.clear()
    linia.clear()
    kierunek.clear()
    na_zywo.clear()
    # tak moglem to zapisac jakos lepiej i nie, nie chce mi sie
    try:
        online(URL="https://gtfs.ztp.krakow.pl/TripUpdates_A.pb")
        online(URL="https://gtfs.ztp.krakow.pl/TripUpdates_M.pb")
    except requests.exceptions.RequestException as e:
        os.system('cls' if os.name == 'nt' else 'clear') # antywindows bugfix
        print(str(time) + " >> last update")
        print("Error: ", e)
        print("Brawo Kraków ! ! !")
        return False
    offline(GTFS_KRK_A, "krk")
    offline(GTFS_KRK_M, "krk")
    if kml == "1":
        offline(GTFS_KML, "kml")

    os.system('cls' if os.name == 'nt' else 'clear')
    print(str(time) + " >> Last update")
    
    all_data = {"czas": [], "linia": [], "kierunek": [], "na_zywo": []}
    upcoming_trips.sort(key=lambda x: x[0])
    for _, arrival_str, line, dest, trip_id, live, tstop in upcoming_trips:
        line = line or "??"  # fallback gdyby nie bylo
        dest = dest or "??"
        status = "LIVE" if live else "SCHEDULE"
        tstop = kml_stop_ids.get(tstop, tstop)
        tstop = tstop[-2:]
        #print(f"{arrival_str} >> {line} >> {dest} >> {status} >> {trip_id} >> {tstop}")
        if tstop not in stops_data:
            stops_data[tstop] = {"czas": [], "linia": [], "kierunek": [], "na_zywo": []} #
        if len(stops_data[tstop]["czas"]) < 4:
            stops_data[tstop]["czas"].append(arrival_str) # sortowanie danych do odpowienich katergorii
            stops_data[tstop]["linia"].append(line)
            stops_data[tstop]["kierunek"].append(dest)
            stops_data[tstop]["na_zywo"].append(status)
            if direction == tstop:
                print(f"{arrival_str} >> {line} >> {dest} >> {status}")

            if len(all_data["czas"]) < 4:
                all_data["czas"].append(arrival_str)  # 00
                all_data["linia"].append(line)
                all_data["kierunek"].append(dest)
                all_data["na_zywo"].append(status)
                if direction == "00":
                    print(f"{arrival_str} >> {line} >> {dest} >> {status}")

    db.reference("00").set(all_data) # zapisanie 00
    root_ref = db.reference()
    for stop_id, data in stops_data.items(): # tworzenie folderow 00 01 itp
        root_ref.child(stop_id).set(data) # np. w 01 daje wszystko
    return True

while 1 < 2:
    main()
    p = 0
    while p < 20:
        czasczas = str(time_nosec)
        czasczas = czasczas[:-3]
        czasczas_dir.set(czasczas)
        time_module.sleep(1)
        p = p + 1
