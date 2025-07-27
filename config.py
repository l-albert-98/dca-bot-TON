import os
import json

def get_env_var(name):
    value = os.getenv(name)
    if not value:
        raise ValueError(f"{name} not set in environment variables")
    return value

BINANCE_API_KEY = "2jqmH9ynEHBFBHs1svWLvC2ArykdtHbkia8S7QWhGWGArC1WDIARkTLUW6tnwTun"
BINANCE_API_SECRET = "D6XUsvXVvmJouVwA6EAnpJ3IgN4SCb1A8sCjieeWpZADwkR2GcfGa7k3vtkbIU9a"
TELEGRAM_TOKEN = "7636114962:AAFuPGF8fLtX8BRoH2tvJ7lffgpAAWCpP3A"
TELEGRAM_CHAT_ID = "5148412546"

TRADE_SYMBOLS = get_env_var("TRADE_SYMBOLS").split(",")
TRADE_BUDGETS = json.loads(get_env_var("TRADE_BUDGETS"))
TRADE_INTERVAL = int(get_env_var("TRADE_INTERVAL"))
