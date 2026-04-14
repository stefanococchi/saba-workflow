# Setup Saba Workflow - Guida Passo-Passo

## 📋 Prerequisiti

- Python 3.9+
- PostgreSQL 12+
- pgAdmin (o psql)
- Account email con SMTP (es. Gmail)

---

## 🚀 Setup Iniziale

### 1. Clona il progetto

```bash
cd progetti/
# Il progetto saba-workflow è già presente
cd saba-workflow
```

### 2. Crea virtual environment

```bash
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# oppure
venv\Scripts\activate  # Windows
```

### 3. Installa dipendenze

```bash
pip install -r requirements.txt
```

---

## 🗄️ Setup Database

### 4. Crea database PostgreSQL

**Opzione A - Via pgAdmin:**
1. Apri pgAdmin
2. Crea nuovo database: `saba_workflow`
3. Owner: postgres (o altro utente)

**Opzione B - Via psql:**
```bash
psql -U postgres
CREATE DATABASE saba_workflow;
\q
```

### 5. Configura variabili ambiente

Copia il file `.env.example` in `.env`:

```bash
cp .env.example .env
```

Modifica `.env` con i tuoi dati:

```env
# Database (modifica se necessario)
DATABASE_URL=postgresql://postgres:TUA_PASSWORD@localhost:5432/saba_workflow

# SMTP - Esempio Gmail
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=tua-email@gmail.com
SMTP_PASSWORD=tua-app-password  # Vedi nota sotto
SMTP_FROM_EMAIL=tua-email@gmail.com
SMTP_FROM_NAME=Il Tuo Nome

# Secret keys (genera stringhe random)
SECRET_KEY=genera-stringa-casuale-qui
JWT_SECRET_KEY=altra-stringa-casuale-qui
```

**📧 Nota Gmail:**
- Non usare la password normale!
- Vai su: https://myaccount.google.com/apppasswords
- Genera "App password" per SMTP
- Usa quella password nel file .env

### 6. Inizializza Alembic e crea tabelle

```bash
# Genera migrazione iniziale
alembic revision --autogenerate -m "Initial schema"

# Applica migrazione
alembic upgrade head
```

Dovresti vedere le tabelle create in pgAdmin:
- workflows
- workflow_steps
- participants
- executions

---

## ✅ Test Setup

### 7. Avvia il server

```bash
python run.py
```

Dovresti vedere:
```
INFO:__main__:Avvio Saba Workflow su porta 5001
INFO:__main__:Debug mode: True
 * Running on http://0.0.0.0:5001
```

### 8. Test health check

Apri un altro terminale:

```bash
curl http://localhost:5001/api/health
```

Risposta attesa:
```json
{
  "status": "ok",
  "database": "connected"
}
```

### 9. Test completo con script

```bash
python test_workflow.py
```

Questo script:
1. Crea un workflow di test
2. Aggiunge 2 partecipanti
3. NON invia email (per sicurezza)

**⚠️ Per testare l'invio email:**
1. Apri `test_workflow.py`
2. Alla riga ~150 circa, decommentare:
   ```python
   response = requests.post(f"{BASE_URL}/api/workflows/{workflow_id}/start")
   ```
3. Esegui di nuovo: `python test_workflow.py`
4. Controlla email in arrivo!

---

## 🔗 Uso da saba-form

Una volta avviato saba-workflow su `localhost:5001`, da saba-form puoi fare:

```python
import requests

# Crea workflow
response = requests.post('http://localhost:5001/api/workflows', json={
    'name': 'Invito Cliente',
    'steps': [...]
})

workflow_id = response.json()['id']

# Aggiungi partecipanti
requests.post(f'http://localhost:5001/api/workflows/{workflow_id}/participants', json={
    'participants': [{'email': 'cliente@example.com', 'name': 'Mario Rossi'}]
})

# Avvia
requests.post(f'http://localhost:5001/api/workflows/{workflow_id}/start')
```

---

## 🐛 Troubleshooting

### Server non parte
- Verifica porta 5001 libera: `lsof -i :5001`
- Controlla DATABASE_URL in .env

### Errore database connection
- PostgreSQL è avviato? `pg_isready`
- Password corretta in .env?
- Database `saba_workflow` esiste?

### Email non partono
- SMTP_USER e SMTP_PASSWORD corretti?
- Se Gmail: hai generato App Password?
- Firewall blocca porta 587?

### Alembic errori
- `.env` esiste e DATABASE_URL è corretto?
- Elimina `migrations/versions/*.py` e rigenera:
  ```bash
  rm migrations/versions/*.py
  alembic revision --autogenerate -m "Initial schema"
  alembic upgrade head
  ```

---

## 📚 Prossimi Step

1. ✅ Setup completato
2. Personalizza template email in `app/templates/emails/`
3. Crea workflow custom via API
4. Integra con saba-form

---

## 🆘 Supporto

In caso di problemi, controlla:
- Logs del server (output di `python run.py`)
- File `.env` configurato correttamente
- PostgreSQL attivo e accessibile
