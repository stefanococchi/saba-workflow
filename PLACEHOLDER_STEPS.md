# Workflow Steps - Implementation Roadmap

## Overview

This document describes all available workflow steps in saba-workflow, including both **implemented** and **placeholder** features.

---

## ✅ Implemented Steps

### 1. Email Step
**Status:** ✅ Fully Working

**Purpose:** Send templated emails to participants

**Configuration:**
- Subject line
- HTML body template with Jinja2 variables
- Delay hours (wait before sending)
- Optional landing page for data collection

**Variables available:**
- `{{participant.name}}`
- `{{participant.email}}`
- `{{landing_url}}` (if landing page enabled)

**Backend:** `app/services/email_service.py`

---

### 2. Delay Step
**Status:** ✅ Fully Working (integrated into Email Step)

**Purpose:** Wait X hours before executing next step

**Configuration:**
- Hours to wait (integer)

**Note:** Currently delay is configured inside each Email Step (`delay_hours` field). A standalone Delay block exists in UI but is not saved to backend.

---

## ⭐ Placeholder Steps (Not Yet Implemented)

These steps are **visible in the UI** but do not execute. They will be implemented based on user needs.

---

### 3. Condition Step - FULL
**Status:** ⭐ Placeholder

**Purpose:** Branch workflow into 2 paths based on participant data

**Proposed Configuration:**
```json
{
  "field": "interest_level",
  "operator": "equals",
  "value": "high",
  "if_true_branch": [4, 5, 6],
  "if_false_branch": [7, 8]
}
```

**Implementation Requirements:**
- Database: Add `next_step_if_true` and `next_step_if_false` to `workflow_steps` table
- UI: Visual branch editor (2 separate canvas areas)
- Backend: Modify `SchedulerService._schedule_next_step()` to evaluate condition
- Evaluation: Implement JSONLogic or custom evaluator

**Estimated Effort:** 6-8 hours

**Use Cases:**
- Send different emails based on survey responses
- Segment users by behavior (clicked link vs didn't click)
- Personalized paths (enterprise vs small business)

---

### 4. Wait Until Step
**Status:** ⭐ Placeholder

**Purpose:** Wait until specific date/time instead of delay hours

**Proposed Configuration:**
```json
{
  "wait_type": "date",          // date, time, day_of_week
  "target_date": "2026-05-15",  // specific date
  "target_time": "09:00",       // specific time
  "timezone": "Europe/Rome"
}
```

**Implementation Requirements:**
- Modify `SchedulerService.schedule_step()` to support `run_date` parameter
- Add timezone handling (pytz library)
- UI: Date/time picker in modal

**Estimated Effort:** 1-2 hours

**Use Cases:**
- Event reminders ("send 2 days before event")
- Time-sensitive campaigns ("send every Monday at 9am")
- Seasonal campaigns ("start on Black Friday")

---

### 5. Goal Check Step
**Status:** ⭐ Placeholder

**Purpose:** Check if participant reached goal, stop or continue workflow

**Proposed Configuration:**
```json
{
  "goal": "form_submitted",     // or email_opened, link_clicked, etc.
  "if_met": "complete",          // complete workflow
  "if_not_met": "continue"       // continue to next step
}
```

**Implementation Requirements:**
- Add goal tracking to `participants` table (e.g., `goals_reached` JSON field)
- Backend: Check goal status in execution
- UI: Goal selector dropdown

**Estimated Effort:** 2-3 hours

**Use Cases:**
- Stop sending emails after form submission
- Escalate if no engagement after 3 emails
- Convert "completed" participants to different workflow

---

### 6. Engagement Tracker Step
**Status:** ⭐ Placeholder

**Purpose:** Track email opens and clicks, trigger actions based on engagement

**Proposed Configuration:**
```json
{
  "track_opens": true,
  "track_clicks": true,
  "action_on_open": "mark_engaged",
  "action_on_no_open_hours": 48,
  "fallback_action": "send_different_email"
}
```

**Implementation Requirements:**
- Add tracking pixel to emails (1x1 transparent image)
- Webhook endpoint `/track/open/{token}` and `/track/click/{token}`
- Update `executions` table with `opened_at`, `clicked_at` timestamps
- Modify scheduler to check engagement before next step

**Estimated Effort:** 3-4 hours

**Use Cases:**
- Send reminder only to those who didn't open
- Prioritize leads who clicked links
- A/B test email subject lines

---

### 7. Survey Step
**Status:** ⭐ Placeholder

**Purpose:** Multi-question survey with conditional logic

**Proposed Configuration:**
```json
{
  "questions": [
    {
      "id": "q1",
      "type": "multiple_choice",
      "text": "What interests you?",
      "options": ["Product A", "Product B", "Both"]
    },
    {
      "id": "q2",
      "type": "text",
      "text": "Tell us more",
      "show_if": {"q1": "Both"}
    }
  ],
  "submit_url": "/survey/submit/{token}"
}
```

**Implementation Requirements:**
- New landing page template for surveys
- JavaScript for conditional show/hide questions
- Backend: Survey response storage in `collected_data`
- UI: Visual survey builder (drag questions)

**Estimated Effort:** 6-8 hours

**Use Cases:**
- NPS surveys
- Product feedback
- Lead qualification
- Event registration with custom fields

---

### 8. File Upload Step
**Status:** ⭐ Placeholder

**Purpose:** Request participant to upload documents

**Proposed Configuration:**
```json
{
  "required_files": ["ID Document", "Proof of Address"],
  "max_size_mb": 10,
  "allowed_types": ["pdf", "jpg", "png"],
  "storage": "s3",               // or local
  "bucket": "saba-uploads"
}
```

**Implementation Requirements:**
- File upload landing page with dropzone
- Storage integration (S3 boto3 or local filesystem)
- Virus scanning (ClamAV or similar)
- Backend: Track uploaded files in `collected_data`

**Estimated Effort:** 4-5 hours

**Use Cases:**
- KYC document collection
- Resume uploads for job applications
- Contract signing workflows
- Expense report submissions

---

### 9. Human Approval Step
**Status:** ⭐ Placeholder

**Purpose:** Pause workflow until human approves

**Proposed Configuration:**
```json
{
  "approver_email": "manager@example.com",
  "approval_message": "Review participant data before continuing",
  "timeout_hours": 48,
  "on_approve": "continue",
  "on_reject": "cancel",
  "on_timeout": "auto_approve"
}
```

**Implementation Requirements:**
- Email notification to approver with approve/reject links
- Admin UI page: `/admin/approvals` listing pending approvals
- Backend: Pause execution, resume on approval
- Add `approval_status` field to `executions` table

**Estimated Effort:** 3-4 hours

**Use Cases:**
- Manager approval for discounts
- Legal review before contract send
- Manual verification of high-value leads
- Compliance checks

---

### 10. Export Data Step
**Status:** ⭐ Placeholder

**Purpose:** Export collected data to CSV/Excel

**Proposed Configuration:**
```json
{
  "format": "csv",               // csv, excel, json
  "fields": ["name", "email", "responses", "status"],
  "send_to": "admin@example.com",
  "schedule": "daily",           // or on_complete
  "filename": "workflow_{date}.csv"
}
```

**Implementation Requirements:**
- CSV generation with pandas/csv module
- Excel generation with openpyxl
- Email attachment sending
- Scheduled export (cron-like)

**Estimated Effort:** 2-3 hours

**Use Cases:**
- Daily reports of participants
- Export for external CRM import
- Backup of collected data
- Analytics and reporting

---

## Implementation Priority

### Phase 1: Quick Wins (1-2 weeks)
1. **Wait Until Step** (1-2h)
2. **Goal Check Step** (2-3h)
3. **Export Data Step** (2-3h)

**Total:** ~7 hours

### Phase 2: Medium Complexity (2-3 weeks)
4. **Engagement Tracker** (3-4h)
5. **File Upload Step** (4-5h)
6. **Human Approval Step** (3-4h)

**Total:** ~12 hours

### Phase 3: Complex Features (1 month)
7. **Condition Step - FULL** (6-8h)
8. **Survey Step** (6-8h)

**Total:** ~14 hours

---

## How to Request Implementation

When you need a specific placeholder step:

1. **Identify use case** - What problem are you solving?
2. **Provide example data** - Sample participant data, expected flow
3. **Priority** - How urgently do you need it?
4. **Open issue** - Document requirements

**We implement features as they're needed, not speculatively.**

---

## Testing Placeholder Steps

You can:
- ✅ Drag placeholder steps to canvas
- ✅ Edit their configuration (saves as JSON)
- ✅ Save workflow with placeholders
- ⚠️ **Workflow will skip placeholder steps during execution**
- ⚠️ Warning shown when saving workflow with placeholders

---

## Current Workflow Execution Behavior

When workflow encounters placeholder step:
1. Logs warning: `"Step {id} type {type} not supported - skipping"`
2. Continues to next step
3. Marks execution as `SKIPPED` in database

No errors thrown, workflow continues normally.

---

## Questions?

- Check `/admin/workflows/{id}` to see placeholder steps marked with ⭐
- Placeholder steps have dashed borders in canvas
- Edit modal shows "Placeholder Feature" warning

**Bottom line:** UI shows what's possible, backend implements what's needed. 🚀
