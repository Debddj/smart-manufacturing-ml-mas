import requests

def send_telegram_alert(message):
    # Your credentials
    bot_token = "8596031542:AAHJXct-OD8_Y09OBtj3WvDA1iNccW6dkC4"
    chat_id = "6039778809"
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML" # Optional: allows you to use <b>bold</b> etc.
    }

    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()  # Check if the request was successful
        print("Telegram alert sent successfully!")
        return True
    except requests.exceptions.HTTPError as err:
        print(f"HTTP Error: {err}")
    except Exception as e:
        print(f"Error occurred: {e}")
    return False

if __name__ == "__main__":
    send_telegram_alert("🚀 <b>Supply Chain MAS Alert:</b> Test message successful.")
