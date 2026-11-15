"""
main.py
-------
Universal entry point for bot-hosting platforms (Render, Pterodactyl, Railway, etc.)
Launches Moonlit Quest Bot v2 with an integrated Render health-check server and error logging.
"""
import os
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# Ensure current directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Moonlit Bot is alive and running!")

def run_server():
    port = int(os.environ.get("PORT", 10000))
    server_address = ('0.0.0.0', port)
    httpd = HTTPServer(server_address, HealthCheckHandler)
    print(f"Health-check server listening on port {port}", flush=True)
    httpd.serve_forever()

if __name__ == "__main__":
    try:
        import bot
        bot._acquire_instance_lock()
        
        if not bot.BOT_TOKEN:
            print("ERROR: BOT_TOKEN is not set in environment variables!", flush=True)
            sys.exit(1)
        
        # Background health-check server start karein
        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()

        print(f"Starting {bot.BOT_NAME} on Render...", flush=True)
        bot.bot.run(bot.BOT_TOKEN)
    except Exception as e:
        print(f"[CRITICAL STARTUP ERROR] {e}", flush=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)
