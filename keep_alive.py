from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return '''
    <html>
    <head><title>Music Bot</title></head>
    <body style="background:#1a1a2e;color:white;text-align:center;padding:50px;font-family:Arial;">
        <h1>🎵 Music Bot Online!</h1>
        <p>Status: ✅ Running</p>
    </body>
    </html>
    '''

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()
