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

    result = {}

    # -----------------------------
    # CAS OEM 20 BYTES FIXE
    # -----------------------------
    if len(data) == 20:
        result["format"] = "OEM_20B"

        result["stroke_rate"] = data[2] / 2.0
        result["stroke_count"] = int.from_bytes(data[3:5], "little")
        result["total_distance"] = int.from_bytes(data[5:7], "little")
        result["calories"] = data[12]
        result["elapsed_time"] = int.from_bytes(data[18:20], "little")

        return result

    # -----------------------------
    # FTMS STANDARD
    # -----------------------------
    result["format"] = "FTMS"

    flags = int.from_bytes(data[0:2], "little")
    result["flags_hex"] = f"0x{flags:04X}"

    offset = 2

    # Champs obligatoires
    result["stroke_rate"] = data[offset] / 2.0
    offset += 1

    result["stroke_count"] = int.from_bytes(data[offset:offset+2], "little")
    offset += 2

    # Champs optionnels dynamiques

    if flags & (1 << 1):  # Average Stroke Rate
        result["avg_stroke_rate"] = data[offset] / 2.0
        offset += 1

    if flags & (1 << 2):  # Total Distance
        result["total_distance"] = int.from_bytes(data[offset:offset+3], "little")
        offset += 3

    if flags & (1 << 3):  # Instantaneous Pace
        result["inst_pace"] = int.from_bytes(data[offset:offset+2], "little")
        offset += 2

    if flags & (1 << 4):  # Average Pace
        result["avg_pace"] = int.from_bytes(data[offset:offset+2], "little")
        offset += 2

    if flags & (1 << 5):  # Instantaneous Power
        result["inst_power"] = int.from_bytes(
            data[offset:offset+2], "little", signed=True
        )
        offset += 2

    if flags & (1 << 6):  # Average Power
        result["avg_power"] = int.from_bytes(
            data[offset:offset+2], "little", signed=True
        )
        offset += 2

    if flags & (1 << 7):  # Resistance Level
        result["resistance"] = data[offset]
        offset += 1

    if flags & (1 << 8):  # Total Energy
        result["total_energy"] = int.from_bytes(data[offset:offset+2], "little")
        offset += 2

    if flags & (1 << 9):  # Energy per Hour
        result["energy_per_hour"] = int.from_bytes(data[offset:offset+2], "little")
        offset += 2

    if flags & (1 << 10):  # Energy per Minute
        result["energy_per_min"] = data[offset]
        offset += 1

    if flags & (1 << 11):  # Elapsed Time
        result["elapsed_time"] = int.from_bytes(data[offset:offset+2], "little")
        offset += 2

    if flags & (1 << 12):  # Remaining Time
        result["remaining_time"] = int.from_bytes(data[offset:offset+2], "little")
        offset += 2

    if flags & (1 << 13):  # Heart Rate
        result["heart_rate"] = data[offset]
        offset += 1

    if flags & (1 << 14):  # MET
        result["met"] = data[offset] / 10.0
        offset += 1

    result["packet_length"] = len(data)

    return result



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
                    parsed = parse_ftms(data)

                    # Affichage console complet
                    print("---- FRAME ----")
                    for k, v in parsed.items():
                        print(f"{k}: {v}")

                    # Envoi bridge (valeurs sécurisées)
                    dist = parsed.get("total_distance", 0)
                    time_val = parsed.get("elapsed_time", 0)
                    power = parsed.get("inst_power", 0)
                    strokes = parsed.get("stroke_count", 0)
                    cal = parsed.get("total_energy", 0)

                    msg = f"dist={dist};time={time_val};effort={power};strokes={strokes};calories={cal}"
                    sock.sendto(msg.encode(), (UDP_IP, UDP_PORT))
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
