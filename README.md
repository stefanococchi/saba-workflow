# Saba Workflow

Sistema modulare per gestione workflow di comunicazione con partecipanti.

## Caratteristiche

- ✉️ Invio email multi-step con template personalizzabili
- 📋 Landing page dinamiche per raccolta dati
- ⏱️ Scheduling automatico follow-up
- 🔐 Token criptati JWT per sicurezza
- 📊 Tracking stato partecipanti

## Setup

### 1. Ambiente virtuale

```bash
cd saba-workflow
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows
```

### 2. Installazione dipendenze

```bash
pip install -r requirements.txt
```

### 3. Configurazione database

Crea file `.env`:

```env
DATABASE_URL=postgresql://user:password@localhost:5432/saba_workflow
SECRET_KEY=your-secret-key-here
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-password
```

### 4. Inizializza database

```bash
# Crea database in Postgres (via pgAdmin o psql)
CREATE DATABASE saba_workflow;

# Applica migrazioni
alembic upgrade head
```

### 5. Avvia server

```bash
python run.py
```

Server disponibile su: `http://localhost:5001`

## Uso da saba-form

```python
import requests

# Crea workflow
response = requests.post('http://localhost:5001/api/workflows', json={
    'name': 'Invito Evento',
    'steps': [
        {
            'order': 1,
            'type': 'email',
            'template': 'invito_iniziale',
            'delay_hours': 0
        },
        {
            'order': 2,
            'type': 'email',
            'template': 'sollecito_1',
            'delay_hours': 72
        }
    ]
})

workflow_id = response.json()['id']

# Aggiungi partecipanti
requests.post(f'http://localhost:5001/api/workflows/{workflow_id}/participants', json={
    'participants': [
        {'email': 'user@example.com', 'name': 'Mario Rossi'}
    ]
})

# Avvia workflow
requests.post(f'http://localhost:5001/api/workflows/{workflow_id}/start')
```

## Struttura progetto

```
saba-workflow/
├── app/
│   ├── models/           # SQLAlchemy models
│   ├── services/         # Business logic
│   ├── api/              # REST endpoints
│   └── templates/        # Jinja2 templates
├── migrations/           # Alembic migrations
├── config.py            # Configurazione
├── run.py               # Entry point
└── VERSION              # Versione progetto
```

## Versioning

Formato: `vMAJOR.MINOR.JULIAN_DAY.PROGRESSIVE`

Esempio: `v1.0.103.1`
- 1 = Major version
- 0 = Minor version  
- 103 = Giorno giuliano (13 aprile)
- 1 = Progressivo giornaliero

**Prima di ogni commit aggiornare VERSION!**

## API Endpoints

### Workflows
- `POST /api/workflows` - Crea workflow
- `GET /api/workflows` - Lista workflows
- `GET /api/workflows/{id}` - Dettaglio workflow
- `PUT /api/workflows/{id}` - Aggiorna workflow
- `DELETE /api/workflows/{id}` - Elimina workflow

### Partecipanti
- `POST /api/workflows/{id}/participants` - Aggiungi partecipanti
- `GET /api/workflows/{id}/participants` - Lista partecipanti
- `POST /api/workflows/{id}/start` - Avvia workflow

### Landing page
- `GET /landing/{token}` - Mostra form raccolta dati
- `POST /landing/{token}` - Submit dati partecipante

## Testing locale

```bash
# Test API
curl http://localhost:5001/api/health

# Expected: {"status": "ok"}
```

## Deploy

**NON fare deploy senza testare in locale prima!**

Istruzioni deploy verranno aggiunte successivamente.
