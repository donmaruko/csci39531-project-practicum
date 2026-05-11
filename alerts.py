import smtplib
from email.message import EmailMessage

from config import SMTP_FROM, SMTP_PASSWORD, SMTP_HOST, SMTP_PORT


def build_email_body(event):
    """
    @param event: normalized event dict from _extract_event
    @return: formatted plain text email body string
    """
    is_presale = event["effective_status"] == "presale"
    kind = "PRESALE ALERT" if is_presale else "ON SALE ALERT"
    lines = [f"[{kind}]", ""]

    date_line = f"Date:    {event['date']}"
    if event.get("show_time"):
        date_line += f"  {event['show_time']}"
    lines += [
        f"Event:   {event['name']}",
        date_line,
        f"Venue:   {event['venue']}, {event['city']}",
    ]

    if event.get("support"):
        lines.append(f"Support: {', '.join(event['support'])}")
    if is_presale:
        presale_open = event["presale_start_dt"].strftime("%b %d, %Y") if event.get("presale_start_dt") else None
        status_line = "Status:  PRESALE"
        if presale_open:
            status_line += f" — presale opens {presale_open}"
        if event.get("presale_label"):
            status_line += f" + general public on sale {event['presale_label']}"
        lines.append(status_line)
    if event.get("address"):
        lines.append(f"Address: {event['address']}" + (f"  (Timezone: {event['timezone']})" if event.get("timezone") else ""))
    if event.get("social"):
        for platform, url in event["social"].items():
            lines.append(f"{platform.capitalize()}: {url}")

    lines += ["", f"URL:     {event['url']}", "", "have fun !"]
    return "\n".join(lines)


def send_email_alert(event, recipient):
    """
    @param event: normalized event dict from _extract_event
    @param recipient: destination email address string
    @pre: SMTP_FROM, SMTP_PASSWORD, SMTP_HOST, SMTP_PORT are set in the environment
    @post: sends an on sale or presale alert email to recipient via SMTP_SSL,
           or skips if credentials are missing
    """
    if not all([SMTP_FROM, SMTP_PASSWORD, recipient]):
        return

    prefix = "PRESALE" if event["effective_status"] == "presale" else "ON SALE"

    msg = EmailMessage()
    msg["Subject"] = f"{prefix}: {event['name']} — {event['date']} @ {event['venue']}"
    msg["From"] = SMTP_FROM
    msg["To"] = recipient
    msg.set_content(build_email_body(event))

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.login(SMTP_FROM, SMTP_PASSWORD)
        smtp.send_message(msg)