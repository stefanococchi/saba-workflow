"""
Export Service - Generate CSV/Excel exports of workflow data
"""
import csv
from io import StringIO
from datetime import datetime
from app import db_session as db
from app.models import Participant, Workflow
from app.services.email_service import EmailService
import logging

logger = logging.getLogger(__name__)


class ExportService:
    """Service for exporting workflow participant data"""
    
    @staticmethod
    def export_workflow_csv(workflow_id, send_to_email=None):
        """
        Export workflow participants to CSV
        
        Args:
            workflow_id: ID of workflow to export
            send_to_email: Optional email to send CSV to
            
        Returns:
            tuple: (success: bool, csv_content: str, filename: str)
        """
        try:
            workflow = db.get(Workflow, workflow_id)
            if not workflow:
                logger.error(f"Workflow {workflow_id} not found")
                return (False, None, None)
            
            # Get all participants
            participants = db.query(Participant).filter_by(workflow_id=workflow_id).all()
            
            if not participants:
                logger.warning(f"No participants found for workflow {workflow_id}")
                return (False, None, None)
            
            # Generate CSV
            output = StringIO()
            
            # Determine all possible fields from collected_data
            all_fields = set()
            for p in participants:
                if p.collected_data:
                    all_fields.update(p.collected_data.keys())
            
            # CSV headers
            headers = ['ID', 'First Name', 'Last Name', 'Email', 'Status', 'Created At', 'Last Interaction']
            headers.extend(sorted(all_fields))  # Add dynamic fields from collected_data
            
            writer = csv.writer(output)
            writer.writerow(headers)
            
            # Write participant data
            for p in participants:
                row = [
                    p.id,
                    p.first_name,
                    p.last_name,
                    p.email,
                    p.status.value,
                    p.created_at.isoformat() if p.created_at else '',
                    p.last_interaction.isoformat() if p.last_interaction else ''
                ]
                
                # Add collected_data fields
                for field in sorted(all_fields):
                    value = p.collected_data.get(field, '') if p.collected_data else ''
                    row.append(value)
                
                writer.writerow(row)
            
            csv_content = output.getvalue()
            filename = f"workflow_{workflow_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
            
            logger.info(f"✓ Generated CSV for workflow {workflow_id}: {len(participants)} participants")
            
            # Send via email if requested
            if send_to_email:
                ExportService._send_csv_email(
                    to_email=send_to_email,
                    csv_content=csv_content,
                    filename=filename,
                    workflow_name=workflow.name
                )
            
            return (True, csv_content, filename)
            
        except Exception as e:
            logger.error(f"✗ Error generating CSV: {str(e)}")
            return (False, None, None)
    
    @staticmethod
    def _send_csv_email(to_email, csv_content, filename, workflow_name):
        """
        Send CSV as email attachment
        
        Args:
            to_email: Recipient email
            csv_content: CSV file content
            filename: Filename for attachment
            workflow_name: Name of workflow
        """
        try:
            import smtplib
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            from email.mime.base import MIMEBase
            from email import encoders
            from config import Config
            
            # Create message
            msg = MIMEMultipart()
            msg['From'] = Config.SMTP_USER
            msg['To'] = to_email
            msg['Subject'] = f"Workflow Export: {workflow_name}"
            
            # Email body
            body = f"""
            <html>
            <body>
                <h2>Workflow Data Export</h2>
                <p>Attached is the CSV export for workflow: <strong>{workflow_name}</strong></p>
                <p>Generated at: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
                <p>This is an automated export from Saba Workflow.</p>
            </body>
            </html>
            """
            
            msg.attach(MIMEText(body, 'html'))
            
            # Attach CSV
            attachment = MIMEBase('application', 'octet-stream')
            attachment.set_payload(csv_content.encode('utf-8'))
            encoders.encode_base64(attachment)
            attachment.add_header('Content-Disposition', f'attachment; filename={filename}')
            msg.attach(attachment)
            
            # Send email
            with smtplib.SMTP(Config.SMTP_HOST, Config.SMTP_PORT) as server:
                server.starttls()
                server.login(Config.SMTP_USER, Config.SMTP_PASSWORD)
                server.send_message(msg)
            
            logger.info(f"✓ CSV sent via email to {to_email}")
            return True
            
        except Exception as e:
            logger.error(f"✗ Error sending CSV email: {str(e)}")
            return False
    
    @staticmethod
    def save_csv_file(csv_content, filename, output_dir='/tmp'):
        """
        Save CSV to file system
        
        Args:
            csv_content: CSV content
            filename: Filename
            output_dir: Directory to save to
            
        Returns:
            str: Full filepath or None
        """
        try:
            import os
            
            filepath = os.path.join(output_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(csv_content)
            
            logger.info(f"✓ CSV saved to {filepath}")
            return filepath
            
        except Exception as e:
            logger.error(f"✗ Error saving CSV file: {str(e)}")
            return None
