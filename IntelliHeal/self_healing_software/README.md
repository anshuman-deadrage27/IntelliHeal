IntelliHeal - Self-Healing Software (hardware-compatible)

How to run (basic):
1. Create a virtual environment:
   python -m venv venv
   source venv/bin/activate   # or .\venv\Scripts\Activate.ps1 on Windows PowerShell

2. Install dependencies:
   pip install -r requirements.txt

3. (Optional) Run ai_model/train_model.py to create a tiny model mapping:
   python ai_model/train_model.py

4. Start the app:
   python main.py

5. Open http://127.0.0.1:8000/ui in your browser to view the simple demo UI.

Notes:
- By default HAL adapter is in TCP mode and expects a simulator on 127.0.0.1:9000 streaming newline-delimited JSON messages (heartbeats).
- To test without hardware, create a small TCP simulator that periodically sends heartbeat JSON messages for tile ids "tile_0"..."tile_31".
- To extend to serial or real hardware, implement HALAdapter methods to read/write serial frames and adapt the message formats.
