"""Stripe Checkout integration with extensive audit logging."""

import stripe
import logging
import hashlib
import time
from datetime import datetime
from flask import current_app
import app as _app
from app.models import PaymentLog, PaymentStatus

logger = logging.getLogger(__name__)


def _db():
    return _app.db_session


class PaymentError(Exception):
    """Errore specifico pagamento."""
    pass


class PaymentService:

    @staticmethod
    def _configure_stripe():
        """Set Stripe API key. Called before every Stripe API call."""
        stripe.api_key = current_app.config['STRIPE_SECRET_KEY']

    @staticmethod
    def create_checkout_session(
        participant_id: int,
        workflow_id: int,
        step_id: int,
        amount_cents: int,
        currency: str,
        description: str,
        success_url: str,
        cancel_url: str,
        participant_email: str = None,
        idempotency_key: str = None,
    ) -> dict:
        """
        Create a Stripe Checkout Session.

        Returns:
            dict with 'checkout_url' and 'session_id'
        Raises:
            PaymentError on failure
        """
        PaymentService._configure_stripe()

        logger.info(
            f"STRIPE: Creating checkout session | participant={participant_id} "
            f"step={step_id} amount={amount_cents}c {currency} idempotency={idempotency_key}"
        )

        try:
            params = {
                'payment_method_types': ['card', 'paypal'],
                'line_items': [{
                    'price_data': {
                        'currency': currency,
                        'unit_amount': amount_cents,
                        'product_data': {
                            'name': description or 'Payment',
                        },
                    },
                    'quantity': 1,
                }],
                'mode': 'payment',
                'success_url': success_url,
                'cancel_url': cancel_url,
                'metadata': {
                    'participant_id': str(participant_id),
                    'workflow_id': str(workflow_id),
                    'step_id': str(step_id),
                },
                'expires_at': int(time.time()) + 1800,  # 30 minutes
            }

            if participant_email:
                params['customer_email'] = participant_email

            kwargs = {}
            if idempotency_key:
                kwargs['idempotency_key'] = idempotency_key

            session = stripe.checkout.Session.create(**params, **kwargs)

            logger.info(
                f"STRIPE: Checkout session created | session={session.id} "
                f"participant={participant_id} amount={amount_cents}c {currency}"
            )

            # Log INITIATED in PaymentLog
            PaymentService.log_payment(
                participant_id=participant_id,
                workflow_id=workflow_id,
                step_id=step_id,
                stripe_session_id=session.id,
                amount_cents=amount_cents,
                currency=currency,
                status=PaymentStatus.INITIATED,
            )

            return {
                'checkout_url': session.url,
                'session_id': session.id,
            }

        except stripe.StripeError as e:
            logger.error(
                f"STRIPE ERROR: Failed to create checkout | participant={participant_id} "
                f"step={step_id} error={str(e)}",
                exc_info=True,
            )
            # Log FAILED
            PaymentService.log_payment(
                participant_id=participant_id,
                workflow_id=workflow_id,
                step_id=step_id,
                stripe_session_id=None,
                amount_cents=amount_cents,
                currency=currency,
                status=PaymentStatus.FAILED,
                error_message=str(e),
            )
            raise PaymentError(f"Stripe error: {str(e)}")

    @staticmethod
    def verify_checkout_session(session_id: str) -> dict:
        """
        Retrieve and verify a Checkout Session from Stripe.

        Returns:
            dict with payment details (amount_total, currency, payment_intent, payment_status)
        Raises:
            PaymentError if session not found or not paid
        """
        PaymentService._configure_stripe()

        logger.info(f"STRIPE: Verifying checkout session | session={session_id}")

        try:
            session = stripe.checkout.Session.retrieve(session_id)
        except stripe.StripeError as e:
            logger.error(f"STRIPE ERROR: Failed to retrieve session {session_id}: {e}", exc_info=True)
            raise PaymentError(f"Cannot retrieve session: {str(e)}")

        if session.payment_status != 'paid':
            logger.warning(
                f"STRIPE: Session {session_id} not paid | status={session.payment_status}"
            )
            raise PaymentError(f"Payment not completed. Status: {session.payment_status}")

        logger.info(
            f"STRIPE: Session verified | session={session_id} "
            f"payment_intent={session.payment_intent} "
            f"amount={session.amount_total}c {session.currency}"
        )

        return {
            'amount_total': session.amount_total,
            'currency': session.currency,
            'payment_intent': session.payment_intent,
            'payment_status': session.payment_status,
            'customer_email': session.customer_details.email if session.customer_details else None,
        }

    @staticmethod
    def construct_webhook_event(payload: bytes, sig_header: str):
        """
        Verify webhook signature and construct event.

        Returns:
            stripe.Event
        Raises:
            ValueError on invalid signature
        """
        webhook_secret = current_app.config['STRIPE_WEBHOOK_SECRET']
        if not webhook_secret:
            raise ValueError("STRIPE_WEBHOOK_SECRET not configured")

        PaymentService._configure_stripe()
        return stripe.Webhook.construct_event(payload, sig_header, webhook_secret)

    @staticmethod
    def generate_idempotency_key(participant_id: int, step_id: int) -> str:
        """
        Deterministic idempotency key: participant + step + date + attempt count.
        Prevents double-charging within the same attempt, but allows retries after rollback.
        """
        # Count existing INITIATED payments for this participant+step today
        attempt = 0
        try:
            attempt = _db().query(PaymentLog).filter_by(
                participant_id=participant_id,
                step_id=step_id,
                status=PaymentStatus.INITIATED,
            ).count()
        except Exception:
            pass
        date_str = datetime.utcnow().strftime('%Y-%m-%d')
        raw = f"pay_{participant_id}_{step_id}_{date_str}_a{attempt}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    @staticmethod
    def log_payment(
        participant_id: int,
        workflow_id: int,
        step_id: int,
        stripe_session_id: str = None,
        stripe_payment_intent_id: str = None,
        stripe_event_id: str = None,
        amount_cents: int = 0,
        currency: str = 'eur',
        status: PaymentStatus = None,
        stripe_event_type: str = None,
        error_message: str = None,
        raw_event: dict = None,
    ) -> PaymentLog:
        """Create a PaymentLog entry. Never raises -- logs errors internally."""
        try:
            # Dedup: skip if same stripe_event_id already exists
            if stripe_event_id:
                existing = _db().query(PaymentLog).filter_by(
                    stripe_event_id=stripe_event_id
                ).first()
                if existing:
                    logger.info(f"STRIPE: Duplicate event skipped | event_id={stripe_event_id}")
                    return existing

            entry = PaymentLog(
                participant_id=participant_id,
                workflow_id=workflow_id,
                step_id=step_id,
                stripe_session_id=stripe_session_id,
                stripe_payment_intent_id=stripe_payment_intent_id,
                stripe_event_id=stripe_event_id,
                amount_cents=amount_cents,
                currency=currency,
                status=status,
                stripe_event_type=stripe_event_type,
                error_message=error_message,
                raw_event=raw_event,
                created_at=datetime.utcnow(),
            )
            _db().add(entry)
            _db().commit()

            logger.info(
                f"STRIPE: PaymentLog created | id={entry.id} status={status.value} "
                f"participant={participant_id} session={stripe_session_id} "
                f"amount={amount_cents}c {currency}"
            )
            return entry

        except Exception as e:
            logger.error(f"STRIPE ERROR: Failed to create PaymentLog: {e}", exc_info=True)
            try:
                _db().rollback()
            except Exception:
                pass
            return None

    @staticmethod
    def has_successful_payment(participant_id: int, step_id: int) -> bool:
        """Check if participant already has a successful payment for this step."""
        try:
            return _db().query(PaymentLog).filter_by(
                participant_id=participant_id,
                step_id=step_id,
                status=PaymentStatus.COMPLETED,
            ).first() is not None
        except Exception as e:
            logger.error(f"STRIPE ERROR: has_successful_payment check failed: {e}")
            return False
