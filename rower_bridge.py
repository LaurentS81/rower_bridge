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

    # Cas 1 : Format fixe 20 octets (JOROTO / OEM chinois)
    if len(data) == 20:
        effort = data[2]
        strokes = int.from_bytes(data[3:5], "little")
        distance = int.from_bytes(data[5:7], "little")
        calories = data[12]
        active_time = int.from_bytes(data[18:20], "little")

        return distance, active_time, effort, strokes, calories

    # Cas 2 : FTMS standard (flags dynamiques)
    flags = int.from_bytes(data[0:2], "little")
    offset = 2

    stroke_rate = data[offset]
    offset += 1

    stroke_count = int.from_bytes(data[offset:offset+2], "little")
    offset += 2

    total_distance = None
    total_energy = None
    elapsed_time = None
    power = None

    if flags & (1 << 2):
        total_distance = int.from_bytes(data[offset:offset+3], "little")
        offset += 3

    if flags & (1 << 5):
        power = int.from_bytes(data[offset:offset+2], "little", signed=True)
        offset += 2

    if flags & (1 << 7):
        total_energy = int.from_bytes(data[offset:offset+2], "little")
        offset += 2

    if flags & (1 << 12):
        elapsed_time = int.from_bytes(data[offset:offset+2], "little")
        offset += 2

    return total_distance, elapsed_time, power, stroke_count, total_energy



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
