"""Stripe webhook handler with signature verification and event processing."""

import logging
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app
import app as _app
from app.models import PaymentLog, PaymentStatus, Participant, WorkflowStep, ParticipantStatus
from app.services.payment_service import PaymentService
from app.services.activity_service import log_activity

logger = logging.getLogger(__name__)

stripe_bp = Blueprint('stripe', __name__)


def _db():
    return _app.db_session


@stripe_bp.route('/stripe/webhook', methods=['POST'])
def stripe_webhook():
    """
    Handle Stripe webhook events.

    CRITICAL: This endpoint must:
    1. Verify cryptographic signature (reject if invalid)
    2. Be idempotent (handle duplicate events)
    3. Return 200 quickly
    4. Log everything
    """
    payload = request.get_data()
    sig_header = request.headers.get('Stripe-Signature', '')

    # 1. Verify signature
    try:
        event = PaymentService.construct_webhook_event(payload, sig_header)
    except ValueError as e:
        logger.error(f"STRIPE WEBHOOK: Invalid signature rejected | error={e}")
        return jsonify({'error': 'Invalid signature'}), 400
    except Exception as e:
        logger.error(f"STRIPE WEBHOOK: Unexpected error verifying signature: {e}", exc_info=True)
        return jsonify({'error': 'Verification failed'}), 400

    event_type = event.type
    event_id = event.id
    logger.info(f"STRIPE WEBHOOK: Received {event_type} | event_id={event_id}")

    # 2. Check for duplicate event
    existing = _db().query(PaymentLog).filter_by(stripe_event_id=event_id).first()
    if existing:
        logger.info(f"STRIPE WEBHOOK: Duplicate event skipped | event_id={event_id}")
        return jsonify({'received': True, 'duplicate': True}), 200

    # 3. Handle event types
    try:
        if event_type == 'checkout.session.completed':
            _handle_checkout_completed(event)
        elif event_type == 'checkout.session.expired':
            _handle_checkout_expired(event)
        elif event_type == 'charge.refunded':
            _handle_charge_refunded(event)
        elif event_type == 'charge.dispute.created':
            _handle_dispute_created(event)
        elif event_type == 'payment_intent.payment_failed':
            _handle_payment_failed(event)
        else:
            logger.info(f"STRIPE WEBHOOK: Unhandled event type {event_type}")
    except Exception as e:
        logger.error(f"STRIPE WEBHOOK: Error handling {event_type}: {e}", exc_info=True)
        # Still return 200 to prevent Stripe from retrying
        return jsonify({'received': True, 'error': str(e)}), 200

    return jsonify({'received': True}), 200


def _extract_metadata(session_obj):
    """Extract participant_id, workflow_id, step_id from Stripe session metadata."""
    meta = session_obj.get('metadata', {}) or {}
    return {
        'participant_id': int(meta['participant_id']) if meta.get('participant_id') else None,
        'workflow_id': int(meta['workflow_id']) if meta.get('workflow_id') else None,
        'step_id': int(meta['step_id']) if meta.get('step_id') else None,
    }


def _sanitize_event(event) -> dict:
    """Return a sanitized copy of the event for storage (remove sensitive card details)."""
    try:
        data = event.to_dict() if hasattr(event, 'to_dict') else dict(event)
        # Remove potentially sensitive nested data
        obj = data.get('data', {}).get('object', {})
        for key in ('payment_method_details', 'source', 'customer_details'):
            if key in obj:
                obj[key] = '[REDACTED]'
        return data
    except Exception:
        return {'event_id': event.id, 'type': event.type}


def _handle_checkout_completed(event):
    """
    Reconciliation safety net: if the success redirect failed,
    this webhook ensures the payment is still recorded.
    """
    session = event.data.object
    session_id = session.id
    meta = _extract_metadata(session)

    logger.info(
        f"STRIPE WEBHOOK: checkout.session.completed | session={session_id} "
        f"participant={meta['participant_id']} amount={session.amount_total}c"
    )

    if not meta['participant_id']:
        logger.warning(f"STRIPE WEBHOOK: No participant_id in metadata for session {session_id}")
        return

    # Check if payment was already processed via success redirect
    existing_completed = _db().query(PaymentLog).filter_by(
        stripe_session_id=session_id,
        status=PaymentStatus.COMPLETED,
    ).first()

    if existing_completed:
        # Already processed via redirect - just log the webhook event for audit
        PaymentService.log_payment(
            participant_id=meta['participant_id'],
            workflow_id=meta['workflow_id'],
            step_id=meta['step_id'],
            stripe_session_id=session_id,
            stripe_payment_intent_id=session.payment_intent,
            stripe_event_id=event.id,
            amount_cents=session.amount_total,
            currency=session.currency,
            status=PaymentStatus.COMPLETED,
            stripe_event_type='checkout.session.completed',
            raw_event=_sanitize_event(event),
        )
        logger.info(f"STRIPE WEBHOOK: Payment already processed for session {session_id} (reconciliation OK)")
        return

    # Payment NOT yet processed - this is the safety net
    logger.warning(
        f"STRIPE WEBHOOK: Payment not yet recorded! Processing via webhook | "
        f"session={session_id} participant={meta['participant_id']}"
    )

    participant = _db().query(Participant).filter_by(
        id=meta['participant_id']
    ).with_for_update().first()

    if not participant:
        logger.error(f"STRIPE WEBHOOK: Participant {meta['participant_id']} not found!")
        return

    # Update collected_data with payment info
    existing_data = dict(participant.collected_data or {})
    existing_data.pop('_payment_pending', None)
    existing_data['_payment'] = {
        'status': 'completed',
        'amount_cents': session.amount_total,
        'currency': session.currency,
        'stripe_session_id': session_id,
        'stripe_payment_intent_id': session.payment_intent,
        'paid_at': datetime.utcnow().isoformat(),
        'processed_via': 'webhook',
    }
    participant.collected_data = existing_data
    participant.last_interaction = datetime.utcnow()

    # Log PaymentLog
    PaymentService.log_payment(
        participant_id=meta['participant_id'],
        workflow_id=meta['workflow_id'],
        step_id=meta['step_id'],
        stripe_session_id=session_id,
        stripe_payment_intent_id=session.payment_intent,
        stripe_event_id=event.id,
        amount_cents=session.amount_total,
        currency=session.currency,
        status=PaymentStatus.COMPLETED,
        stripe_event_type='checkout.session.completed',
        raw_event=_sanitize_event(event),
    )

    # Log ActivityLog
    log_activity(
        workflow_id=meta['workflow_id'],
        event_type='payment_completed',
        description=f'{participant.full_name or participant.email} paid {session.amount_total / 100:.2f} {session.currency.upper()} (via webhook)',
        participant_id=meta['participant_id'],
        step_id=meta['step_id'],
        details={
            'stripe_session_id': session_id,
            'amount_cents': session.amount_total,
            'processed_via': 'webhook',
        },
    )

    _db().commit()

    # Execute branching logic
    if meta['step_id']:
        from app.services.scheduler_service import SchedulerService
        step = _db().get(WorkflowStep, meta['step_id'])
        if step:
            config = step.skip_conditions or {}
            if_success = config.get('payment_if_success', config.get('landing_if_filled', 'continue'))
            if_success_step = config.get('payment_if_success_step', config.get('landing_if_filled_step', 0))
            SchedulerService._handle_landing_branch(participant, step, if_success, if_success_step)


def _handle_checkout_expired(event):
    """Session expired without payment."""
    session = event.data.object
    session_id = session.id
    meta = _extract_metadata(session)

    logger.warning(
        f"STRIPE WEBHOOK: checkout.session.expired | session={session_id} "
        f"participant={meta['participant_id']}"
    )

    if not meta['participant_id']:
        return

    PaymentService.log_payment(
        participant_id=meta['participant_id'],
        workflow_id=meta['workflow_id'],
        step_id=meta['step_id'],
        stripe_session_id=session_id,
        stripe_event_id=event.id,
        amount_cents=session.amount_total or 0,
        currency=session.currency or 'eur',
        status=PaymentStatus.EXPIRED,
        stripe_event_type='checkout.session.expired',
        raw_event=_sanitize_event(event),
    )

    log_activity(
        workflow_id=meta['workflow_id'],
        event_type='payment_expired',
        description=f'Payment session expired for participant {meta["participant_id"]}',
        participant_id=meta['participant_id'],
        step_id=meta['step_id'],
    )

    # Clean up _payment_pending flag
    participant = _db().get(Participant, meta['participant_id'])
    if participant:
        existing_data = dict(participant.collected_data or {})
        if existing_data.pop('_payment_pending', None):
            participant.collected_data = existing_data
            _db().commit()


def _handle_charge_refunded(event):
    """Refund issued from Stripe Dashboard."""
    charge = event.data.object
    payment_intent_id = charge.payment_intent

    logger.warning(
        f"STRIPE WEBHOOK: charge.refunded | payment_intent={payment_intent_id} "
        f"amount_refunded={charge.amount_refunded}c"
    )

    # Find the original payment by payment_intent_id
    original = _db().query(PaymentLog).filter_by(
        stripe_payment_intent_id=payment_intent_id,
        status=PaymentStatus.COMPLETED,
    ).first()

    if not original:
        logger.warning(f"STRIPE WEBHOOK: No completed payment found for intent {payment_intent_id}")
        return

    PaymentService.log_payment(
        participant_id=original.participant_id,
        workflow_id=original.workflow_id,
        step_id=original.step_id,
        stripe_session_id=original.stripe_session_id,
        stripe_payment_intent_id=payment_intent_id,
        stripe_event_id=event.id,
        amount_cents=charge.amount_refunded,
        currency=charge.currency,
        status=PaymentStatus.REFUNDED,
        stripe_event_type='charge.refunded',
        raw_event=_sanitize_event(event),
    )

    log_activity(
        workflow_id=original.workflow_id,
        event_type='payment_refunded',
        description=f'Payment refunded: {charge.amount_refunded / 100:.2f} {charge.currency.upper()}',
        participant_id=original.participant_id,
        step_id=original.step_id,
        details={
            'amount_refunded_cents': charge.amount_refunded,
            'payment_intent_id': payment_intent_id,
        },
    )

    # Update collected_data
    participant = _db().get(Participant, original.participant_id)
    if participant:
        existing_data = dict(participant.collected_data or {})
        if existing_data.get('_payment'):
            existing_data['_payment']['status'] = 'refunded'
            existing_data['_payment']['refunded_at'] = datetime.utcnow().isoformat()
            participant.collected_data = existing_data
            _db().commit()


def _handle_dispute_created(event):
    """Chargeback initiated."""
    dispute = event.data.object
    payment_intent_id = dispute.payment_intent

    logger.error(
        f"STRIPE WEBHOOK: DISPUTE CREATED | payment_intent={payment_intent_id} "
        f"amount={dispute.amount}c reason={dispute.reason}"
    )

    original = _db().query(PaymentLog).filter_by(
        stripe_payment_intent_id=payment_intent_id,
        status=PaymentStatus.COMPLETED,
    ).first()

    if not original:
        logger.warning(f"STRIPE WEBHOOK: No completed payment found for disputed intent {payment_intent_id}")
        return

    PaymentService.log_payment(
        participant_id=original.participant_id,
        workflow_id=original.workflow_id,
        step_id=original.step_id,
        stripe_session_id=original.stripe_session_id,
        stripe_payment_intent_id=payment_intent_id,
        stripe_event_id=event.id,
        amount_cents=dispute.amount,
        currency=dispute.currency,
        status=PaymentStatus.DISPUTED,
        stripe_event_type='charge.dispute.created',
        error_message=dispute.reason,
        raw_event=_sanitize_event(event),
    )

    log_activity(
        workflow_id=original.workflow_id,
        event_type='payment_disputed',
        description=f'DISPUTE: {dispute.amount / 100:.2f} {dispute.currency.upper()} - {dispute.reason}',
        participant_id=original.participant_id,
        step_id=original.step_id,
        details={
            'amount_cents': dispute.amount,
            'reason': dispute.reason,
            'payment_intent_id': payment_intent_id,
        },
    )


def _handle_payment_failed(event):
    """Payment attempt failed."""
    intent = event.data.object
    payment_intent_id = intent.id
    error_msg = ''
    if intent.last_payment_error:
        error_msg = intent.last_payment_error.get('message', '')

    logger.warning(
        f"STRIPE WEBHOOK: payment_intent.payment_failed | intent={payment_intent_id} "
        f"error={error_msg}"
    )

    meta = intent.get('metadata', {}) or {}
    participant_id = int(meta['participant_id']) if meta.get('participant_id') else None
    workflow_id = int(meta['workflow_id']) if meta.get('workflow_id') else None
    step_id = int(meta['step_id']) if meta.get('step_id') else None

    if not participant_id:
        # Try to find via existing PaymentLog
        existing = _db().query(PaymentLog).filter_by(
            stripe_payment_intent_id=payment_intent_id,
        ).first()
        if existing:
            participant_id = existing.participant_id
            workflow_id = existing.workflow_id
            step_id = existing.step_id

    if participant_id:
        PaymentService.log_payment(
            participant_id=participant_id,
            workflow_id=workflow_id,
            step_id=step_id,
            stripe_payment_intent_id=payment_intent_id,
            stripe_event_id=event.id,
            amount_cents=intent.amount or 0,
            currency=intent.currency or 'eur',
            status=PaymentStatus.FAILED,
            stripe_event_type='payment_intent.payment_failed',
            error_message=error_msg,
            raw_event=_sanitize_event(event),
        )

        log_activity(
            workflow_id=workflow_id,
            event_type='payment_failed',
            description=f'Payment failed: {error_msg}',
            participant_id=participant_id,
            step_id=step_id,
            details={'error': error_msg, 'payment_intent_id': payment_intent_id},
        )
