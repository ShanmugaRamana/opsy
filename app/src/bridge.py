# app/src/bridge.py
import webview
import urllib.request
from .config import FRONTEND_URL, SHUTDOWN_URL, MAIN_WIDTH, MAIN_HEIGHT

class Api:
    def __init__(self):
        self.splash_window = None

    def splash_complete(self):
        # Create the main app window
        main_window = webview.create_window(
            'Opsy', 
            FRONTEND_URL,
            width=MAIN_WIDTH,
            height=MAIN_HEIGHT
        )
        main_window.events.closed += self.on_main_window_closed

        # Close the splash window
        if self.splash_window:
            self.splash_window.destroy()

    def on_main_window_closed(self):
        try:
            req = urllib.request.Request(SHUTDOWN_URL, method='POST')
            urllib.request.urlopen(req)
            print("Frontend server shut down successfully.")
        except Exception as e:
            print(f"Could not shut down frontend server: {e}")
