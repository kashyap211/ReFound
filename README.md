# ReFound - Find it. Track it. Reunite it.

## 1. What is ReFound?
ReFound is an **IoT-based smart lost-and-found system**. A Raspberry Pi 3 Model B+ (camera, IR sensor, push button, buzzer, LEDs, OLED) will detect items and send them to a web dashboard. This first version is the **website and backend**, running on a laptop with demo data. No real hardware is connected yet, and the dashboard says so.

## 2. Architecture
```
Raspberry Pi -> Sensors/Camera -> Detection -> Database (SQLite) -> Flask Backend -> Web Dashboard
```
The Pi sends JSON to the Flask API. Flask validates it, stores it in SQLite, and the pages read from the same database.

## 3. Folder structure
```
ReFound/
├── app.py              Flask app: routes, API, database code
├── database.db        created automatically on first run
├── requirements.txt   (only Flask)
├── README.md
├── templates/         base, index, items, item_detail, detections, settings (+ _macros.html helpers)
├── static/css/style.css  static/js/script.js  static/images/placeholder.svg
└── uploads/           uploaded + demo images
```

## 4. Required software
Python 3.9+ (check with `python --version`). Nothing else - no Node.js, no paid APIs.

## 5-6. Virtual environment
```
cd ReFound
python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate       # macOS / Linux / Raspberry Pi
```

## 7. Install dependencies
```
pip install -r requirements.txt
```

## 8. Initialize the database
Automatic. When `app.py` starts it creates `database.db`, the tables (`items`, `detections`, `settings`) and loads 8 demo items on the first run. To reset, stop the server and delete `database.db`.

## 9-10. Run and open
```
python app.py
```
Open **http://127.0.0.1:5000** in your browser.

## 11. Demo data
- First run: 8 demo items load automatically (black wallet, smartphone, keychain, backpack, and more) with locally generated placeholder pictures.
- Dashboard -> **Simulate a detection** adds a new fake Pi detection (needs demo mode ON).
- Settings -> **Load demo data** re-adds missing demo items; **Demo mode** switches simulated hardware status on or off.

## 12. Image upload
Items page -> **Add a new item** -> choose a photo. Only PNG/JPG/GIF/WEBP up to 5 MB are accepted. The name is cleaned with `secure_filename`, given a random prefix and saved in `uploads/`. The database stores only the filename. Items without a photo show a placeholder.

## 13. API documentation
If you set an environment variable `REFOUND_API_TOKEN`, every POST to the API must include the header `X-API-Token: <token>`.

| Method | URL | Purpose |
|---|---|---|
| POST | `/api/detection` | Record a detection (JSON, or form data with an `image` file) |
| GET | `/api/items` | List all items |
| GET | `/api/detections` | List detection history |
| GET | `/api/system-status` | Current hardware status |
| POST | `/api/system-status` | Pi reports its hardware health |
| POST | `/item/<id>/status` | Change status (form, or JSON `{"status":"Claimed"}`) |
| POST | `/item/<id>/delete` | Delete an item and its detections |

`POST /api/detection` body (`name` required; `category` one of Mobile Phone, Wallet, Keys, Bag, ID Card, Watch, Other; `status` one of Found, Pending, Claimed, Unclaimed):
```json
{"name": "Wallet", "category": "Wallet", "description": "Black wallet detected", "location": "Room 101", "status": "Found"}
```
Success (201): `{"message":"Detection recorded","detection_id":9,"detection_code":"DET-0009","item_id":9,"recorded_at":"..."}`
Errors: 400 with `details` list, 401 if the token is wrong.

Test from a terminal:
```
curl -X POST http://127.0.0.1:5000/api/detection -H "Content-Type: application/json" -d "{\"name\":\"Wallet\",\"category\":\"Wallet\",\"description\":\"Black wallet detected\",\"location\":\"Room 101\",\"status\":\"Found\"}"
curl http://127.0.0.1:5000/api/items
curl http://127.0.0.1:5000/api/system-status
```
(On Windows PowerShell use `curl.exe`, or the Python example below.)

## 14. How the Raspberry Pi will connect
Both devices must be on the same Wi-Fi. The Pi runs a Python script that, when the IR sensor triggers and the camera takes a photo, sends it to the laptop/Pi server. Plug your sensor code in at the marked comments:
```python
import json, urllib.request

SERVER = "http://192.168.1.50:5000"   # IP of the computer running ReFound

def send_detection(name, category, description, location):
    body = json.dumps({"name": name, "category": category, "description": description,
                       "location": location, "status": "Found"}).encode()
    req = urllib.request.Request(SERVER + "/api/detection", data=body,
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=10))

def send_status(uptime_seconds):
    body = json.dumps({"pi_online": True, "camera_online": True, "ir_active": True,
                       "oled_online": True, "uptime_seconds": uptime_seconds}).encode()
    req = urllib.request.Request(SERVER + "/api/system-status", data=body,
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10)

# --- LATER: your hardware code goes here ---
# 1. Read the IR sensor (gpiozero.DigitalInputDevice)
# 2. Capture a photo (picamera2)  -> optionally upload it as multipart form data with the field "image"
# 3. Identify the object, then call send_detection(...)
# 4. Call send_status(...) every 30-60 seconds so the dashboard shows "Live from Pi"
print(send_detection("Wallet", "Wallet", "Black wallet detected", "Room 101"))
```
In `app.py`, search for "RASPBERRY PI INTEGRATION" (status reports) and "RASPBERRY PI ENDPOINT" (detections). When the Pi sends status reports, the dashboard automatically switches from "Simulated" to "Live from Pi".

## 15. Running on the Raspberry Pi 3 Model B+
1. Install Raspberry Pi OS (it includes Python 3) on the microSD card and connect to Wi-Fi.
2. Copy the `ReFound` folder over (USB drive, `scp -r ReFound pi@<pi-ip>:~/`, or git).
3. On the Pi: `cd ReFound && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt`
4. Start it so other devices can open it: `REFOUND_HOST=0.0.0.0 python app.py`
5. On a phone or laptop in the same network open `http://<pi-ip>:5000` (find the IP with `hostname -I`).
6. Turn demo mode OFF in Settings once the real hardware is connected.

Security notes: it is meant for a trusted local network. Secrets come from environment variables (`REFOUND_SECRET_KEY`, `REFOUND_API_TOKEN`), nothing is hard-coded, all SQL is parameterized, and uploads are restricted and renamed.

## How to test every feature
1. Dashboard shows stats, recent detections, simulated system status and the About workflow.
2. Click **Simulate a detection**: Total Items and Today's Detections go up.
3. Items: search "wallet", filter by category and status, change sort order, then add an item with a photo.
4. Open an item: click Mark as Claimed, Mark as Pending, then Delete Item (a confirmation appears).
5. Detections: filter by date, category and status.
6. Settings: toggle demo mode and check the status values change to Offline.
7. API: run the curl commands above, then refresh the dashboard to see the new detection.
