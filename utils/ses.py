"""Send notification emails to the team via AWS SES.

Trimmed port of the pre-rebuild utils/ses.py: only the team-notification
path survives (welcome/waitlist mail belongs to the signup site, not this
server). Destination is hardwired — this can never email a user or an
arbitrary recipient.

Reads AWS credentials from the environment; falls back to boto3's default
chain (instance role, etc.).
"""

import os

import boto3

from utils.env import load_env

load_env()

TEAM_ADDRESS = "agent@crudecode.dev"


def _get_ses_client():
    key = os.environ.get("AWS_ACCESS_KEY_ID")
    secret = os.environ.get("AWS_SECRET_ACCESS_KEY")
    if key and secret:
        return boto3.client(
            "ses",
            region_name="us-east-1",
            aws_access_key_id=key,
            aws_secret_access_key=secret,
        )
    return boto3.client("ses", region_name="us-east-1")


def send_notification(subject: str, body: str) -> None:
    """Send a plain-text notification to the team mailbox. Raises on failure —
    callers decide whether delivery is best-effort."""
    client = _get_ses_client()
    client.send_email(
        Source=f"Crude Code <{TEAM_ADDRESS}>",
        Destination={"ToAddresses": [TEAM_ADDRESS]},
        Message={
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
        },
    )
