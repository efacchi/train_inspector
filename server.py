from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import requests

app = FastAPI()

# Permetti al frontend di comunicare senza blocchi CORS
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

@app.get("/api/treno/{numero}")
def traccia_treno(numero: str):
    try:
        url_anagrafica = f"http://www.viaggiatreno.it/infomobilita/resteasy/viaggiatreno/cercaNumeroTreno/{numero}"
        res_anagrafica = requests.get(url_anagrafica, headers=HEADERS)
        if res_anagrafica.status_code != 200 or not res_anagrafica.text.strip():
            raise HTTPException(status_code=404, detail="Treno non trovato.")
            
        anagrafica = res_anagrafica.json()
        id_stazione = anagrafica.get("codLocOrig")
        timestamp_partenza = anagrafica.get("millisDataPartenza")

        url_andamento = f"http://www.viaggiatreno.it/infomobilita/resteasy/viaggiatreno/andamentoTreno/{id_stazione}/{numero}/{timestamp_partenza}"
        res_andamento = requests.get(url_andamento, headers=HEADERS)
        dati_treno = res_andamento.json()

        fermate = dati_treno.get("fermate", [])
        
        # Filtriamo SOLO le stazioni commerciali (Fermate 'F' e Arrivo 'A') per la timeline principale
        stazioni_commerciali = []
        for f in fermate:
            if f.get("tipoFermata") in ["F", "A"] or f.get("stazione") == dati_treno.get("origine"):
                orario_reale = f.get("partenzaReale") or f.get("arrivoReale")
                stazioni_commerciali.append({
                    "stazione": f.get("stazione"),
                    "programmata": f.get("partenza_teorica") or f.get("arrivo_teorico"),
                    "reale": orario_reale,
                    "passato": orario_reale is not None or dati_treno.get("arrivato", False),
                    "binarioProgrammato": f.get("binarioProgrammatoPartenzaDescrizione") or f.get("binarioProgrammatoArrivoDescrizione") or "-",
                    "binarioEffettivo": f.get("binarioEffettivoPartenzaDescrizione") or f.get("binarioEffettivoArrivoDescrizione") or "-"
                })

        # Identifichiamo l'ultimo sensore fisico calpestato (che sia stazione o punto tecnico)
        ultimo_rilevamento = {
            "nodo": dati_treno.get("stazioneUltimoRilevamento"),
            "ora": dati_treno.get("compOraUltimoRilevamento"),
            "is_tecnico": True  # Lo verifichiamo nel frontend
        }

        # Se il punto di rilevamento coincide con una stazione commerciale, non è un punto "fantasma" in mezzo alla tratta
        nomi_commerciali = [s["stazione"] for s in stazioni_commerciali]
        if ultimo_rilevamento["nodo"] in nomi_commerciali:
            ultimo_rilevamento["is_tecnico"] = False

        return {
            "numero": dati_treno.get("numeroTreno"),
            "categoria": dati_treno.get("compNumeroTreno", "").split(' ')[1] if dati_treno.get("compNumeroTreno") else "REG",
            "origine": dati_treno.get("origine"),
            "destinazione": dati_treno.get("destinazione"),
            "ritardo": dati_treno.get("ritardo"),
            "statoGenerale": dati_treno.get("compRitardoAndamento", ["-"])[0],
            "arrivato": dati_treno.get("arrivato", False),
            "ultimoRilevamento": ultimo_rilevamento,
            "stazioni": stazioni_commerciali
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Serve i file statici della cartella 'public' (l'HTML) sulla root del sito
app.mount("/", StaticFiles(directory="public", html=True), name="public")