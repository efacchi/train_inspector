from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import requests
import datetime

app = FastAPI()

# Allow frontend to communicate without CORS blocks
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

# Helper to build the English-formatted date string required by ViaggiaTreno for board endpoints.
def get_viaggiatreno_date():
    DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    now = datetime.datetime.now()
    day_name = DAYS[now.weekday()]
    month_name = MONTHS[now.month - 1]
    time_part = now.strftime("%H:%M:%S")
    
    # Retrieve local timezone offset (e.g. +0200 or +0100)
    tz_offset = now.astimezone().strftime('%z')
    if not tz_offset:
        tz_offset = "+0200"
    
    return f"{day_name} {month_name} {now.day:02d} {now.year} {time_part} GMT{tz_offset}"

@app.get("/api/stations/search")
def search_stations(q: str):
    if not q or len(q.strip()) < 2:
        return []
    try:
        url = f"http://www.viaggiatreno.it/infomobilita/resteasy/viaggiatreno/autocompletaStazione/{q.strip()}"
        res = requests.get(url, headers=HEADERS)
        if res.status_code != 200:
            return []
        
        stations = []
        for line in res.text.splitlines():
            line = line.strip()
            if not line or '|' not in line:
                continue
            parts = line.split('|', 1)
            stations.append({
                "name": parts[0].strip(),
                "id": parts[1].strip()
            })
        return stations
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/stations/{station_id}/board")
def get_station_board(station_id: str, direction: str = "departures"):
    try:
        date_str = get_viaggiatreno_date()
        endpoint = "partenze" if direction == "departures" else "arrivi"
        url = f"http://www.viaggiatreno.it/infomobilita/resteasy/viaggiatreno/{endpoint}/{station_id}/{date_str}"
        res = requests.get(url, headers=HEADERS)
        if res.status_code != 200:
            raise HTTPException(status_code=res.status_code, detail="Failed to fetch station board from ViaggiaTreno.")
        
        data = res.json()
        board_items = []
        is_departure = (direction == "departures")
        
        for item in data:
            scheduled_time = item.get("compOrarioPartenza") if is_departure else item.get("compOrarioArrivo")
            scheduled_platform = item.get("binarioProgrammatoPartenzaDescrizione") if is_departure else item.get("binarioProgrammatoArrivoDescrizione")
            actual_platform = item.get("binarioEffettivoPartenzaDescrizione") if is_departure else item.get("binarioEffettivoArrivoDescrizione")
            
            delay = item.get("ritardo", 0)
            status_list = item.get("compRitardo") or item.get("compRitardoAndamento") or ["-"]
            status_desc = status_list[0] if status_list else "-"
            
            departure_timestamp = item.get("dataPartenzaTreno") or item.get("millisDataPartenza")
            
            board_items.append({
                "number": str(item.get("numeroTreno")),
                "category": item.get("categoria", "REG"),
                "destination": item.get("destinazione") if is_departure else None,
                "origin": item.get("origine") if not is_departure else None,
                "scheduledTime": scheduled_time,
                "delay": delay,
                "status": status_desc,
                "scheduledPlatform": scheduled_platform or "-",
                "actualPlatform": actual_platform or "-",
                "originStationId": item.get("codOrigine"),
                "departureTimestamp": departure_timestamp,
                "arrived": item.get("arrivato", False)
            })
            
        return board_items
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/train/{number}")
def track_train(number: str, station_id: str = None, departure_timestamp: int = None):
    try:
        if not station_id or not departure_timestamp:
            info_url = f"http://www.viaggiatreno.it/infomobilita/resteasy/viaggiatreno/cercaNumeroTreno/{number}"
            info_res = requests.get(info_url, headers=HEADERS)
            if info_res.status_code != 200 or not info_res.text.strip():
                raise HTTPException(status_code=404, detail="Train not found.")
                
            info = info_res.json()
            station_id = info.get("codLocOrig")
            departure_timestamp = info.get("millisDataPartenza")

        status_url = f"http://www.viaggiatreno.it/infomobilita/resteasy/viaggiatreno/andamentoTreno/{station_id}/{number}/{departure_timestamp}"
        status_res = requests.get(status_url, headers=HEADERS)
        train_data = status_res.json()

        stops = train_data.get("fermate", [])
        
        # Filter ONLY commercial stations (Stops 'F' and Arrival 'A') for the main timeline
        commercial_stations = []
        for stop in stops:
            if stop.get("tipoFermata") in ["F", "A"] or stop.get("stazione") == train_data.get("origine"):
                actual_time = stop.get("partenzaReale") or stop.get("arrivoReale")
                commercial_stations.append({
                    "station": stop.get("stazione"),
                    "scheduled": stop.get("partenza_teorica") or stop.get("arrivo_teorico"),
                    "actual": actual_time,
                    "passed": actual_time is not None or train_data.get("arrivato", False),
                    "scheduledPlatform": stop.get("binarioProgrammatoPartenzaDescrizione") or stop.get("binarioProgrammatoArrivoDescrizione") or "-",
                    "actualPlatform": stop.get("binarioEffettivoPartenzaDescrizione") or stop.get("binarioEffettivoArrivoDescrizione") or "-"
                })

        # Identify the last physical sensor triggered (whether station or technical point)
        last_detection = {
            "node": train_data.get("stazioneUltimoRilevamento"),
            "time": train_data.get("compOraUltimoRilevamento"),
            "is_technical": True  # We verify it in the frontend
        }

        # If the detection point matches a commercial station, it is not a "ghost" point in the middle of the section
        commercial_names = [s["station"] for s in commercial_stations]
        if last_detection["node"] in commercial_names:
            last_detection["is_technical"] = False

        return {
            "number": train_data.get("numeroTreno"),
            "category": train_data.get("compNumeroTreno", "").split(' ')[1] if train_data.get("compNumeroTreno") else "REG",
            "origin": train_data.get("origine"),
            "destination": train_data.get("destinazione"),
            "delay": train_data.get("ritardo"),
            "generalStatus": train_data.get("compRitardoAndamento", ["-"])[0],
            "arrived": train_data.get("arrivato", False),
            "lastDetection": last_detection,
            "stations": commercial_stations
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Serve static files from 'public' directory (HTML) on the root of the site
app.mount("/", StaticFiles(directory="public", html=True), name="public")