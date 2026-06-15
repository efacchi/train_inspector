from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import requests

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

@app.get("/api/train/{number}")
def track_train(number: str):
    try:
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