# app/src/utils.py
import os

def get_screen_path(filename):
    """Helper to get the absolute path to screens."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, 'screens', filename)

def get_center_position(screen, width, height):
    """Calculate center position based on the primary screen."""
    x_pos = int((screen.width - width) / 2)
    y_pos = int((screen.height - height) / 2)
    return x_pos, y_pos
