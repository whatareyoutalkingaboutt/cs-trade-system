import smtplib
from email.mime.text import MIMEText
from email.header import Header
import os
from loguru import logger

def send_qq_email(subject: str, content: str) -> bool:
    sender = os.getenv("QQ_EMAIL_SENDER")
    password = os.getenv("QQ_EMAIL_AUTH_CODE")
    receiver = os.getenv("QQ_EMAIL_RECEIVER") or sender
    
    if not sender or not password:
        return False

    from email.utils import formataddr
    message = MIMEText(content, "html", "utf-8")
    message["From"] = formataddr((str(Header("套利雷达", "utf-8")), sender))
    message["To"] = formataddr((str(Header("指挥官", "utf-8")), receiver))
    message["Subject"] = Header(subject, "utf-8")

    try:
        server = smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=10)
        server.login(sender, password)
        server.sendmail(sender, [receiver], message.as_string())
        server.quit()
        logger.info("[Email] 告警邮件发送成功")
        return True
    except Exception as e:
        logger.error(f"[Email] 告警邮件发送失败: {e}")
        return False
