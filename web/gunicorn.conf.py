"""Gunicorn hooks — load universe before workers accept traffic."""

def on_starting(server):
    from app_enhanced import load_data

    load_data()
