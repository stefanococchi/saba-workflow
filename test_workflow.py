#!/usr/bin/env python3
"""
Script di test per creare un workflow di esempio
"""
import requests
import json

BASE_URL = "http://localhost:5001"

def test_workflow():
    """Test completo workflow"""
    
    print("=" * 60)
    print("TEST SABA WORKFLOW")
    print("=" * 60)
    
    # 1. Health check
    print("\n1. Health check...")
    response = requests.get(f"{BASE_URL}/api/health")
    print(f"   Status: {response.status_code}")
    print(f"   Response: {response.json()}")
    
    # 2. Crea workflow
    print("\n2. Creazione workflow...")
    workflow_data = {
        "name": "Test Invito Evento",
        "description": "Workflow di test per invito evento",
        "config": {
            "evento": "Workshop Python",
            "data": "15 Maggio 2026",
            "luogo": "Milano"
        },
        "steps": [
            {
                "order": 1,
                "name": "Invito iniziale",
                "type": "email",
                "subject": "Sei invitato al {{ evento }}!",
                "body_template": """
                    <h2>Ciao {{ participant.name }}!</h2>
                    <p>Sei invitato al nostro evento: <strong>{{ evento }}</strong></p>
                    <p>Data: {{ data }}</p>
                    <p>Luogo: {{ luogo }}</p>
                    <p><a href="{{ landing_url }}">Conferma partecipazione</a></p>
                """,
                "delay_hours": 0,
                "landing_page_config": {
                    "fields": [
                        {
                            "name": "nome",
                            "label": "Nome completo",
                            "type": "text",
                            "required": True
                        },
                        {
                            "name": "azienda",
                            "label": "Azienda",
                            "type": "text",
                            "required": False
                        },
                        {
                            "name": "dieta",
                            "label": "Preferenze alimentari",
                            "type": "select",
                            "required": False,
                            "options": [
                                {"value": "normale", "label": "Nessuna preferenza"},
                                {"value": "vegetariano", "label": "Vegetariano"},
                                {"value": "vegano", "label": "Vegano"}
                            ]
                        }
                    ]
                }
            },
            {
                "order": 2,
                "name": "Sollecito 1",
                "type": "email",
                "subject": "Promemoria: {{ evento }}",
                "body_template": """
                    <h2>Ciao {{ participant.name }}!</h2>
                    <p>Non abbiamo ancora ricevuto la tua conferma per {{ evento }}.</p>
                    <p><a href="{{ landing_url }}">Conferma ora</a></p>
                """,
                "delay_hours": 48
            },
            {
                "order": 3,
                "name": "Sollecito finale",
                "type": "email",
                "subject": "Ultima chiamata: {{ evento }}",
                "body_template": """
                    <h2>Ciao {{ participant.name }}!</h2>
                    <p>Questa è l'ultima opportunità per confermare la tua presenza a {{ evento }}!</p>
                    <p><a href="{{ landing_url }}">Conferma subito</a></p>
                """,
                "delay_hours": 72
            }
        ]
    }
    
    response = requests.post(f"{BASE_URL}/api/workflows", json=workflow_data)
    print(f"   Status: {response.status_code}")
    workflow = response.json()
    print(f"   Workflow ID: {workflow['id']}")
    workflow_id = workflow['id']
    
    # 3. Aggiungi partecipanti
    print("\n3. Aggiunta partecipanti...")
    participants_data = {
        "participants": [
            {
                "email": "test1@example.com",
                "name": "Mario Rossi"
            },
            {
                "email": "test2@example.com",
                "name": "Laura Bianchi"
            }
        ]
    }
    
    response = requests.post(
        f"{BASE_URL}/api/workflows/{workflow_id}/participants",
        json=participants_data
    )
    print(f"   Status: {response.status_code}")
    print(f"   Aggiunti: {response.json()['added']} partecipanti")
    
    # 4. Lista workflows
    print("\n4. Lista workflows...")
    response = requests.get(f"{BASE_URL}/api/workflows")
    print(f"   Status: {response.status_code}")
    workflows = response.json()['workflows']
    print(f"   Totale workflows: {len(workflows)}")
    
    # 5. Dettaglio workflow
    print("\n5. Dettaglio workflow...")
    response = requests.get(f"{BASE_URL}/api/workflows/{workflow_id}")
    print(f"   Status: {response.status_code}")
    detail = response.json()
    print(f"   Nome: {detail['name']}")
    print(f"   Steps: {len(detail['steps'])}")
    print(f"   Partecipanti: {detail['participants_count']}")
    
    # 6. Avvia workflow (COMMENTATO - decommentare per testare invio email)
    print("\n6. Avvio workflow...")
    print("   ⚠️  ATTENZIONE: Questa operazione invierà email!")
    print("   ⚠️  Assicurati di aver configurato SMTP in .env")
    print("   ⚠️  Decommentare la riga sotto per avviare")
    
    # response = requests.post(f"{BASE_URL}/api/workflows/{workflow_id}/start")
    # print(f"   Status: {response.status_code}")
    # print(f"   Response: {response.json()}")
    
    print("\n" + "=" * 60)
    print("TEST COMPLETATO!")
    print("=" * 60)
    print(f"\nWorkflow creato con ID: {workflow_id}")
    print(f"Per avviarlo: POST {BASE_URL}/api/workflows/{workflow_id}/start")
    print("\nNOTA: Prima di avviare, configura SMTP in .env!")


if __name__ == "__main__":
    try:
        test_workflow()
    except requests.exceptions.ConnectionError:
        print("\n❌ ERRORE: Server non raggiungibile")
        print("Assicurati che il server sia avviato con: python run.py")
    except Exception as e:
        print(f"\n❌ ERRORE: {str(e)}")
