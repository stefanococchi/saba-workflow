# Prefect Integration Guide

## What is Prefect?

Prefect is a modern workflow orchestration engine that replaces APScheduler in saba-workflow.

**Benefits:**
- ✅ Robust retry logic
- ✅ Task monitoring & logging
- ✅ Conditional branching (ready for future)
- ✅ Cloud dashboard (free tier)
- ✅ Better error handling

---

## Setup Options

### Option A: Prefect Cloud (Recommended - FREE)

**Advantages:**
- Free tier (20,000 task runs/month)
- Cloud dashboard for monitoring
- Zero infrastructure to manage
- Automatic logging & alerts

**Setup:**

1. **Create free Prefect Cloud account:**
   ```bash
   # Go to https://app.prefect.cloud/auth/login
   # Sign up (free)
   ```

2. **Get API key:**
   - Go to https://app.prefect.cloud/my/api-keys
   - Create new API key
   - Copy it

3. **Configure saba-workflow:**
   ```bash
   # In your .env file
   echo "PREFECT_API_KEY=your-api-key-here" >> .env
   echo "PREFECT_API_URL=https://api.prefect.cloud/api/accounts/YOUR_ACCOUNT_ID/workspaces/YOUR_WORKSPACE_ID" >> .env
   ```

4. **Install Prefect:**
   ```bash
   pip install -r requirements.txt
   ```

5. **Login to Prefect:**
   ```bash
   prefect cloud login
   # Paste your API key when prompted
   ```

6. **Test connection:**
   ```bash
   python -c "from prefect import flow; @flow; def test(): print('Works!'); test()"
   ```

---

### Option B: Self-Hosted (FREE but more setup)

**Advantages:**
- Complete control
- No external dependencies
- All data stays local

**Setup:**

1. **Start Prefect server:**
   ```bash
   # Terminal 1 - Start Prefect server
   prefect server start
   ```
   This starts on `http://localhost:4200`

2. **Configure saba-workflow:**
   ```bash
   # In .env
   echo "PREFECT_API_URL=http://localhost:4200/api" >> .env
   ```

3. **Run saba-workflow:**
   ```bash
   # Terminal 2
   python run.py
   ```

---

## Usage in saba-workflow

### Starting a Workflow

**Via Admin UI:**
1. Go to http://localhost:5001/admin/workflows/1
2. Click "Start Workflow"
3. Prefect launches flows for all participants

**Via API:**
```bash
curl -X POST http://localhost:5001/api/workflows/1/start
```

**Response:**
```json
{
  "workflow_id": 1,
  "scheduled": 2,
  "status": "active",
  "engine": "prefect"
}
```

---

## Monitoring

### Prefect Cloud Dashboard

Go to: https://app.prefect.cloud

You'll see:
- **Flow Runs** - Each workflow execution
- **Task Runs** - Each email sent
- **Logs** - Detailed execution logs
- **Failures** - Automatic retry tracking

### Self-Hosted Dashboard

Go to: http://localhost:4200

Same features as Cloud!

---

## How It Works

### Flow Structure

```
start_workflow_for_participants
  ↓
  For each participant:
    ↓
    execute_workflow_flow
      ↓
      For each step:
        ↓
        [delay if needed]
        ↓
        send_email_step
          - Sends email
          - Records execution
          - Handles failures with retry
```

### Retry Logic

Prefect automatically retries failed tasks:
- **Email send fails** → Retry 3 times with 5-min delay
- **Database error** → Retry once with 10-min delay
- **Logs everything** to dashboard

---

## Configuration

### Adjust Retry Settings

Edit `app/services/prefect_engine.py`:

```python
@task(
    retries=5,              # More retries
    retry_delay_seconds=600 # 10 minutes between retries
)
def send_email_step(...):
    ...
```

### Change Delay Behavior

Currently delays are **blocking** (sleeps).

For **scheduled delays** (non-blocking):
```python
from prefect.tasks import exponential_backoff

@task(wait_for=[previous_task], wait=timedelta(hours=48))
def send_reminder(...):
    ...
```

---

## Troubleshooting

### "Connection refused" error

**Solution:**
- Check Prefect server is running: `prefect server start`
- Or configure Prefect Cloud API key

### "Flow not found"

**Solution:**
```bash
# Re-register flows
python -c "from app.services.prefect_engine import deploy_flows; deploy_flows()"
```

### Tasks not executing

**Solution:**
1. Check Prefect dashboard logs
2. Verify `.env` has correct `PREFECT_API_URL`
3. Restart Flask: `python run.py`

---

## Migration from APScheduler

**What changed:**
- ❌ **Removed:** APScheduler background jobs
- ✅ **Added:** Prefect flows and tasks
- ✅ **Better:** Retry logic, monitoring, logging

**Old code (APScheduler):**
```python
SchedulerService.schedule_step(participant, step, delay_hours=48)
```

**New code (Prefect):**
```python
execute_workflow_flow.apply_async(args=[workflow_id, participant_id])
```

**Database:**
- No changes needed!
- Execution records still saved in `executions` table

---

## Cost Breakdown

### Prefect Cloud FREE Tier
- ✅ 20,000 task runs/month
- ✅ 3 months log retention
- ✅ Unlimited users
- ✅ Email alerts

**Your usage estimate:**
- 100 participants/month
- 3 steps per workflow
- = 300 task runs/month
- **Well within free tier!**

### Self-Hosted
- ✅ Completely free
- ✅ Unlimited everything
- ⚠️ You manage the server

---

## Next Steps

1. Choose Cloud or Self-Hosted
2. Follow setup instructions above
3. Test with existing workflow:
   ```bash
   curl -X POST http://localhost:5001/api/workflows/1/start
   ```
4. Check Prefect dashboard to see it running!

---

## Questions?

- Prefect Docs: https://docs.prefect.io
- Prefect Slack: https://prefect.io/slack
- Your logs: Check Prefect dashboard

**Enjoy robust workflows with ZERO cost!** 🚀
