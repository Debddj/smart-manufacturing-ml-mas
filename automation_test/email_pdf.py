import smtplib
from email.mime.text import MIMEText

email = "adityabhowmik68@gmail.com"
password = "kkqz dbkl ikeo wgyw"

msg = MIMEText("Test email body")
msg['From'] = email
msg['To'] = "adityabhowmik68@gmail.com"
msg['Subject'] = "Test Email"

server = smtplib.SMTP('smtp.gmail.com', 587)
server.starttls()
server.login(email, password)
server.sendmail(email, "adityabhowmik68@gmail.com", msg.as_string())
server.quit()
print("Email sent")