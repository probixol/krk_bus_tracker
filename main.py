try:
    import requests
    from google.transit import gtfs_realtime_pb2
except ModuleNotFoundError:
    print("brak protobufa, uruchom: pip install -r requirements.txt")
    exit(1)

import requests, csv, zipfile, math, os, io, sys, threading, socket, sqlite3
import firebase_admin
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import QApplication, QWidget, QGridLayout, QLabel
from PyQt6.QtGui import QFontDatabase, QFont
from firebase_admin import credentials, db
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
GTFS_KRK_A = PROJECT_DIR / "GTFS_KRK_A"
GTFS_KRK_M = PROJECT_DIR / "GTFS_KRK_M"
GTFS_KML = PROJECT_DIR / "ald-gtfs"
CONFIG_FILE = PROJECT_DIR / "CONFIG.txt"
KEY_PATH = PROJECT_DIR / "krk-bus-tracker-firebase-adminsdk-fbsvc-0b46cc464b.json"
DATABASE_URL = 'https://krk-bus-tracker-default-rtdb.europe-west1.firebasedatabase.app'

upcoming_trips = []
ignore_bus = []
stop_ids = []
stop_lat = []
stop_lon = []
kml_stop_ids = {}
block_to_route = {}
block_to_dest = {}
block_to_service = {}
route_to_number = {}
stops_data = {}

socket.setdefaulttimeout(10)
headers = {"User-Agent": "Mozilla/5.0"}

# firebase setup
try:
    cred = credentials.Certificate(str(KEY_PATH))
    firebase_admin.initialize_app(cred, {'databaseURL': DATABASE_URL})
    czasczas_dir = db.reference("00/czasczas")
    przystanek_dir = db.reference("przystanek")
except Exception as e:
    print(f"Błąd Firebase: {e}")
    exit(1)

def internet_available():
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=5)
        return True
    except OSError:
        return False

def parse_gtfs_time(time_str):
    h, m, s = map(int, time_str.split(":"))
    return timedelta(hours=h, minutes=m, seconds=s)

def update_db(base_dir, db_path): # szczerze nie wiem jak to dziala sorry
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS stop_times")
    cursor.execute("CREATE TABLE stop_times (trip_id TEXT, arrival_time TEXT, stop_id TEXT)")
    with (base_dir / "stop_times.txt").open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        to_db = [(r['trip_id'], r['arrival_time'], r['stop_id']) for r in reader]
        cursor.executemany("INSERT INTO stop_times VALUES (?, ?, ?);", to_db)
    cursor.execute("CREATE INDEX idx_stop ON stop_times(stop_id)")
    conn.commit()
    conn.close()

def preload_stop_times(base_dir, system):
    db_path = base_dir / "data.db"
    if not db_path.exists(): update_db(base_dir, db_path)
    active_stop_ids = stop_ids if system == "krk" else list(kml_stop_ids.keys())
    relevant = []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    for s_id in active_stop_ids:
        cursor.execute("SELECT * FROM stop_times WHERE stop_id=?", (s_id,))
        relevant.extend([dict(row) for row in cursor.fetchall()])
    conn.close()
    return relevant

def translator(base_dir):
    with (base_dir / "trips.txt").open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            block_to_route[row["trip_id"]] = row["route_id"]
            block_to_dest[row["trip_id"]] = row["trip_headsign"]
            block_to_service[row["trip_id"]] = row["service_id"]
    with (base_dir / "routes.txt").open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            route_to_number[row["route_id"]] = row["route_short_name"]

def stop_find(base_dir, stop_name, direction_desc):
    with (base_dir / "stops.txt").open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row["stop_name"] == stop_name:
                if row.get("stop_desc") == direction_desc or direction_desc == "00":
                    stop_lat.append(float(row["stop_lat"]))
                    stop_lon.append(float(row["stop_lon"]))
                    stop_ids.append(row["stop_id"])
                    if direction_desc != "00": break

def online(URL):
    if not internet_available(): return
    feed = gtfs_realtime_pb2.FeedMessage()
    try:
        response = requests.get(URL, headers=headers, timeout=10)
        feed.ParseFromString(response.content)
        for entity in feed.entity:
            if entity.HasField("trip_update"):
                tu = entity.trip_update
                for stu in tu.stop_time_update:
                    if stu.stop_id in stop_ids:
                        unix_time = stu.departure.time if stu.HasField("departure") else stu.arrival.time
                        dep_dt = datetime.fromtimestamp(unix_time)
                        diff = dep_dt - datetime.now()
                        minutes = max(0, int(diff.total_seconds() // 60))

                        live_val = 2 if stu.departure.delay // 60 > 5 else 1
                        upcoming_trips.append((
                            timedelta(hours=dep_dt.hour, minutes=dep_dt.minute, seconds=dep_dt.second),
                            f"{minutes} min",
                            route_to_number.get(block_to_route.get(tu.trip.trip_id)),
                            block_to_dest.get(tu.trip.trip_id),
                            tu.trip.trip_id, live_val, stu.stop_id, 0
                        ))
                        ignore_bus.append(tu.trip.trip_id)
    except Exception as e:
        print(f"Online error: {e}")

def offline(preloaded, system):
    now_td = timedelta(hours=datetime.now().hour, minutes=datetime.now().minute)
    today_idx = datetime.weekday(datetime.now())
    active_stop_ids = stop_ids if system == "krk" else kml_stop_ids

    for row in preloaded:
        if row["trip_id"] in ignore_bus: continue
        if row["stop_id"] in active_stop_ids:
            arr_td = parse_gtfs_time(row["arrival_time"])
            if arr_td >= now_td:
                time_diff = arr_td - now_td
                line = route_to_number.get(block_to_route.get(row["trip_id"]))
                dest = block_to_dest.get(row["trip_id"])

                if time_diff < timedelta(hours=1):
                    m = max(0, int(time_diff.total_seconds() // 60))
                    upcoming_trips.append((arr_td, f"{m} min", line, dest, row["trip_id"], 0, row["stop_id"], 0))
                else:
                    upcoming_trips.append(
                        (arr_td, row["arrival_time"][:5], line, dest, row["trip_id"], 0, row["stop_id"], 0))

def display(data):
    while len(data['linia']) < ilosc:
        data['linia'].append("")
        data['kierunek'].append("")
        data['czas'].append("")
        data['na_zywo'].append(0)

    now_str = datetime.now().strftime("%H:%M")
    header_item = layout.itemAtPosition(0, 0)
    if header_item: header_item.widget().setText(now_str)

    for i in range(ilosc):
        line_text = data['linia'][i] or ""
        dest_text = data['kierunek'][i] or ""
        time_text = data['czas'][i] or ""
        status = data['na_zywo'][i]

        if len(dest_text) >= 19: dest_text = dest_text[:18] + "."

        for col, txt in enumerate([line_text, dest_text, time_text]):
            item = layout.itemAtPosition(i + 1, col)
            if item and item.widget():
                lbl = item.widget()
                lbl.setText(txt)
                if status == 1:
                    lbl.setStyleSheet("color: #32CD32;")
                elif status == 2:
                    lbl.setStyleSheet("color: #DB143A;")
                else:
                    lbl.setStyleSheet("color: white;")

def main():
    upcoming_trips.clear()
    ignore_bus.clear()

    try:
        online("https://gtfs.ztp.krakow.pl/TripUpdates_A.pb")
        online("https://gtfs.ztp.krakow.pl/TripUpdates_M.pb")
    except:
        pass

    offline(preloaded_krk_a, "krk")
    offline(preloaded_krk_m, "krk")
    if kml_status == "1": offline(preloaded_kml, "kml")

    upcoming_trips.sort(key=lambda x: x[0])

    seen = set()
    all_data = {"czas": [], "linia": [], "kierunek": [], "na_zywo": []}

    for trip in upcoming_trips:
        key = (trip[0], trip[2], trip[3])
        if key not in seen and len(all_data["linia"]) < ilosc:
            seen.add(key)
            all_data["linia"].append(trip[2])
            all_data["kierunek"].append(trip[3])
            all_data["czas"].append(trip[1])
            all_data["na_zywo"].append(trip[5])

    display(all_data)

    # update firebase
    def fb_up():
        try:
            db.reference("00").set(all_data)
            czasczas_dir.set(datetime.now().strftime("%H:%M"))
        except:
            pass

    threading.Thread(target=fb_up, daemon=True).start()
    return True

# start aplikacji
app = QApplication(sys.argv)
app.setOverrideCursor(Qt.CursorShape.BlankCursor)

# czytanie z config
with CONFIG_FILE.open(encoding="utf-8-sig") as f:
    stop_name = f.readline().strip()
    direction_desc = f.readline().strip()
    kml_status = f.readline().strip()
    font_choice = f.readline().strip()
    ilosc = int(f.readline().strip())

# translacja gtfs
translator(GTFS_KRK_A)
translator(GTFS_KRK_M)
translator(GTFS_KML)
stop_find(GTFS_KRK_A, stop_name, direction_desc)
stop_find(GTFS_KRK_M, stop_name, direction_desc)

# czcionki
font_path = PROJECT_DIR / (
    "Clearview Font.ttf" if font_choice == "1" else "Helvetica.ttf" if font_choice == "2" else "Helvetica-Bold.ttf")
font_id = QFontDatabase.addApplicationFont(str(font_path))
custom_font = QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 91)

# glowne okno
window = QWidget()
window.setFixedSize(1920, 1080)
layout = QGridLayout()
layout.setContentsMargins(20, 20, 20, 20)
window.setLayout(layout)
window.setStyleSheet("background-color: black;")

header_lbl = QLabel("--:--")
header_lbl.setFont(custom_font)
header_lbl.setStyleSheet("color: white;")
layout.addWidget(header_lbl, 0, 0)

for r in range(1, ilosc + 1):
    for c in range(3):
        lbl = QLabel("")
        lbl.setFont(custom_font)
        lbl.setStyleSheet("color: white;")
        layout.addWidget(lbl, r, c)

layout.setColumnStretch(0, 1)
layout.setColumnStretch(1, 20)
layout.setColumnStretch(2, 1)

window.show()

# preload
preloaded_krk_a = preload_stop_times(GTFS_KRK_A, "krk")
preloaded_krk_m = preload_stop_times(GTFS_KRK_M, "krk")
preloaded_kml = preload_stop_times(GTFS_KML, "kml") if kml_status == "1" else []

# aktualny start
main()
timer = QTimer()
timer.timeout.connect(main)
timer.start(30000)  # 30 sekund przerwy

sys.exit(app.exec())
