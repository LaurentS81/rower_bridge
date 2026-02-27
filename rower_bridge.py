#!/usr/bin/env python3
import asyncio
import socket
import time
from bleak import BleakScanner, BleakClient

FTMS_SERVICE_UUID = "00001826-0000-1000-8000-00805f9b34fb"
FTMS_MEASUREMENT_UUID = "00002ad1-0000-1000-8000-00805f9b34fb"
FTMS_CONTROL_POINT_UUID = "00002ad9-0000-1000-8000-00805f9b34fb"

UDP_IP = "127.0.0.1"
UDP_PORT = 5005

RECONNECT_TIMEOUT = 4.0  # Reconnect if no data for 4 seconds

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# cumulés
distance = 0
active_time = 0
strokes = 0
last_move_time = time.time()
last_data_received = time.time()

def parse_ftms(data: bytearray):
    # Octet 2 : effort instantané BRUT
    effort = data[2]

    # Octet 3 : strokes cumulés
    strokes = data[3]

    # Octets 5–6 : distance cumulée (m)
    distance = int.from_bytes(data[5:7], "little")

    # Octet 12 : calories brûlées
    calories = data[12]

    # Octets 18–19 : temps actif matériel (s)
    active_time = int.from_bytes(data[18:20], "little")

    return distance, active_time, effort, strokes, calories



async def connect_and_stream():
    """Connect to rower and stream data, with auto-reconnect on timeout."""
    global last_data_received
    
    while True:
        try:
            print("🔍 Scan BLE...")
            devices = await BleakScanner.discover()

            rower = next(
                (d for d in devices if d.metadata and FTMS_SERVICE_UUID.lower() in
                 [u.lower() for u in d.metadata.get("uuids", [])]),
                None
            )

            if not rower:
                print("❌ Aucun rameur FTMS trouvé, nouvelle tentative...")
                await asyncio.sleep(0.5)
                continue

            print(f"✅ Rameur trouvé : {rower.name}")

            async with BleakClient(rower) as client:
                print("🔗 Connecté")
                last_data_received = time.time()

                async def on_data(_, data):
                    global last_data_received
                    last_data_received = time.time()  # Update timestamp on each frame
                    d, t, e, s, cal = parse_ftms(data)
                    msg = f"dist={d};time={t};effort={e};strokes={s};calories={cal}"
                    sock.sendto(msg.encode(), (UDP_IP, UDP_PORT))
                    print(msg)

                await client.start_notify(FTMS_MEASUREMENT_UUID, on_data)

                await client.write_gatt_char(FTMS_CONTROL_POINT_UUID, bytearray([0x00]), True)
                await client.write_gatt_char(FTMS_CONTROL_POINT_UUID, bytearray([0x07]), True)

                print("📡 Bridge actif")
                
                # Monitor for timeout
                while True:
                    await asyncio.sleep(0.1)  # Check every 100ms
                    time_since_data = time.time() - last_data_received
                    
                    if time_since_data > RECONNECT_TIMEOUT:
                        print(f"⏱️  Pas de trame depuis {time_since_data:.1f}s, reconnexion...")
                        break  # Exit inner loop to reconnect
        
        except asyncio.CancelledError:
            print("🛑 Bridge arrêté")
            break
        except Exception as e:
            print(f"❌ Erreur: {e}, reconnexion...")
            await asyncio.sleep(0.5)

asyncio.run(connect_and_stream())
