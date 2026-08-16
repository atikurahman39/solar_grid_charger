import serial
import json
import requests
import time

SERIAL_PORT = "/dev/serial0"
BAUD_RATE = 115200

API_URL = "http://127.0.0.1:5000/api/data"


def main():

    print("Opening UART...")

    ser = serial.Serial(
        SERIAL_PORT,
        BAUD_RATE,
        timeout=1
    )

    print("UART Ready.")
    print("Waiting for ESP32...")

    while True:

        try:

            line = ser.readline().decode("utf-8").strip()

            if not line:
                continue

            print("Received:", line)

            data = json.loads(line)

            response = requests.post(
                API_URL,
                json=data,
                timeout=5
            )

            print(
                "Sent to Flask:",
                response.status_code
            )

        except json.JSONDecodeError:

            print("Invalid JSON")

        except requests.exceptions.RequestException as e:

            print("API Error:", e)

        except Exception as e:

            print("Error:", e)

        time.sleep(0.05)


if __name__ == "__main__":
    main()

