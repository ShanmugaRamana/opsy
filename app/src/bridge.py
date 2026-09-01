# app/src/bridge.py
import webview
import urllib.request
from .config import FRONTEND_URL, SHUTDOWN_URL, BACKEND_SHUTDOWN_URL, MAIN_WIDTH, MAIN_HEIGHT

class Api:
    def __init__(self):
        self.splash_window = None

    def splash_complete(self, onboarding_required=False):
        # Create the main app window, routed to onboarding if the user hasn't set up yet
        target_url = f'{FRONTEND_URL}/onboarding' if onboarding_required else FRONTEND_URL
        main_window = webview.create_window(
            'Opsy',
            target_url,
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

        try:
            req = urllib.request.Request(BACKEND_SHUTDOWN_URL, method='POST')
            urllib.request.urlopen(req)
            print("Backend server shut down successfully.")
        except Exception as e:
            print(f"Could not shut down backend server: {e}")
