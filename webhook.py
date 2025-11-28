import requests
import os

url: str = os.environ["DISCORD_WEBHOOK_URL"]


request = {"content": "@everyone AKTUALIZACJA KALENDARZA"}

requests.post(url, json=request)
