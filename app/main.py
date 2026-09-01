# app/main.py
import webview
import subprocess
import os

# Fix for WebKitGTK bugs in Linux VMs (like QEMU) 
os.environ['WEBKIT_DISABLE_COMPOSITING_MODE'] = '1'
os.environ['WEBKIT_DISABLE_DMABUF_RENDERER'] = '1'
os.environ['LIBGL_ALWAYS_SOFTWARE'] = '1'

from src.config import SPLASH_WIDTH, SPLASH_HEIGHT, SPLASH_BG_COLOR
from src.utils import get_screen_path, get_center_position
from src.bridge import Api

def start_frontend_server():
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        frontend_dir = os.path.join(os.path.dirname(base_dir), 'frontend')
        subprocess.Popen(['npm', 'start'], cwd=frontend_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("Starting frontend server...")
    except Exception as e:
        print(f"Failed to start frontend server: {e}")

def main():
    start_frontend_server()
    
    # Get the correct file path for the splash HTML
    splash_url = get_screen_path('splash.html')
    
    # Calculate center position based on the primary screen
    screen = webview.screens[0]
    x_pos, y_pos = get_center_position(screen, SPLASH_WIDTH, SPLASH_HEIGHT)
    
    api = Api()

    # Create the splash screen window
    splash_window = webview.create_window(
        'Opsy Loading...', 
        splash_url,
        frameless=True,    # Remove OS window borders
        width=SPLASH_WIDTH, 
        height=SPLASH_HEIGHT,
        x=x_pos,
        y=y_pos,
        resizable=False,
        on_top=True,       # Keep the splash screen above other windows
        background_color=SPLASH_BG_COLOR, # Matches HTML background to prevent white flash
        js_api=api
    )
    api.splash_window = splash_window
    
    # Start the GUI event loop
    webview.start(http_server=True)

if __name__ == '__main__':
    main()
