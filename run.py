"""Development entry point:  python run.py  (or: flask --app run run)."""
from app import create_app

app = create_app()

if __name__ == "__main__":
    host, port = "127.0.0.1", 8050
    print(f"\n  PAW is running →  http://{host}:{port}")
    print("  Open that EXACT address in your browser.")
    print("  (On Windows, 'localhost' can resolve to IPv6 and fail — use 127.0.0.1.)\n")
    app.run(host=host, port=port, debug=True)
