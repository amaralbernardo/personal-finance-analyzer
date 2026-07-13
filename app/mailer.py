"""Email notification helpers."""
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def send_welcome_email(to_email: str, password: str, role: str, app_url: str = "") -> bool:
    """Send a welcome email to a newly created user. Returns True on success."""
    mail_server = os.environ.get("MAIL_SERVER", "")
    mail_port   = int(os.environ.get("MAIL_PORT", "587"))
    mail_user   = os.environ.get("MAIL_USERNAME", "")
    mail_pass   = os.environ.get("MAIL_PASSWORD", "")
    mail_from   = os.environ.get("MAIL_FROM", mail_user)

    if not all([mail_server, mail_user, mail_pass]):
        return False

    role_label = "Administrador" if role == "admin" else "Visualizador"
    login_url  = f"{app_url}/login" if app_url else "a aplicação"

    html = f"""<!DOCTYPE html>
<html lang="pt">
<head><meta charset="UTF-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
             background:#f0f2f5;margin:0;padding:40px 20px;">
  <div style="max-width:520px;margin:0 auto;background:white;border-radius:10px;
              padding:36px 40px;box-shadow:0 1px 4px rgba(0,0,0,.1);">
    <h2 style="margin:0 0 6px;color:#1a1a2e;font-size:1.3rem;">
      Acesso ao Analisador de Finanças Pessoais
    </h2>
    <p style="color:#666;margin:0 0 28px;font-size:.9rem;">
      Foi criada uma conta para ti. Usa as credenciais abaixo para entrar.
    </p>

    <table style="width:100%;border-collapse:collapse;font-size:.9rem;margin-bottom:28px;">
      <tr>
        <td style="padding:10px 0;color:#888;width:120px;">Email</td>
        <td style="padding:10px 0;color:#1a1a2e;font-weight:500;">{to_email}</td>
      </tr>
      <tr style="border-top:1px solid #f0f0f0;">
        <td style="padding:10px 0;color:#888;">Password</td>
        <td style="padding:10px 0;color:#1a1a2e;font-weight:500;font-family:monospace;">{password}</td>
      </tr>
      <tr style="border-top:1px solid #f0f0f0;">
        <td style="padding:10px 0;color:#888;">Papel</td>
        <td style="padding:10px 0;color:#1a1a2e;">{role_label}</td>
      </tr>
    </table>

    <a href="{app_url}/login"
       style="display:inline-block;background:#2d6df6;color:white;text-decoration:none;
              padding:11px 28px;border-radius:7px;font-size:.95rem;font-weight:500;">
      Entrar na aplicação →
    </a>

    <p style="color:#aaa;font-size:.8rem;margin:28px 0 0;">
      Recomendamos que alteres a tua password após o primeiro acesso.
    </p>
  </div>
</body>
</html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Acesso ao Analisador de Finanças Pessoais"
    msg["From"]    = mail_from
    msg["To"]      = to_email
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP(mail_server, mail_port) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(mail_user, mail_pass)
            smtp.sendmail(mail_from, [to_email], msg.as_string())
        return True
    except Exception:
        return False
