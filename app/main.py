# app/main.py
import webview
import os

class Api:
    def __init__(self):
        self.splash_window = None

    def splash_complete(self):
        # Create the main app window
        webview.create_window(
            'Opsy', 
            'http://localhost:3000',
            width=1024,
            height=768
        )
        # Close the splash window
        if self.splash_window:
            self.splash_window.destroy()

def get_screen_path(filename):
    """Helper to get the absolute path to screens. This is useful for PyInstaller packaging later."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return f"file://{os.path.join(base_dir, 'screens', filename)}"

if __name__ == '__main__':
    # Get the correct file path for the splash HTML
    splash_url = get_screen_path('splash.html')
    
    window_width = 400
    window_height = 300

    # Calculate center position based on the primary screen
    screen = webview.screens[0]
    x_pos = int((screen.width - window_width) / 2)
    y_pos = int((screen.height - window_height) / 2)
    
    api = Api()

    # Create the splash screen window
    splash_window = webview.create_window(
        'Opsy Loading...', 
        splash_url,
        frameless=True,    # Remove OS window borders
        width=window_width, 
        height=window_height,
        x=x_pos,
        y=y_pos,
        resizable=False,
        on_top=True,       # Keep the splash screen above other windows
        background_color='#faf5ea', # Matches HTML background to prevent white flash
        js_api=api
    )
    api.splash_window = splash_window
    
    # Start the GUI event loop.
    webview.start()
