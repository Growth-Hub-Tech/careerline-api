"""Email: one interface for every email the API sends.

    from app.email.outbox import send_email
    await send_email(db, to=..., template="contact_acknowledgement", context={...})

send_email renders the email (app/email/templates: one shared layout, one file per email),
stores it in email_outbox and queues a "send_email" background job in the caller's
transaction. The job hands it to the backend chosen by EMAIL_BACKEND (app/email/backends.py):
SMTP in production, the test mailbox on the test server, the log in development.
"""
