# ESP32-S3 WiFi Spatial Mapping — Experiment 01

## Router setup
Use a stable 2.4 GHz SSID (not 5 GHz), fixed channel, fixed router position, and disable band steering if possible. No WiFi password is needed for passive scanning. Set `TARGET_SSID` and optionally `TARGET_BSSID` in the sketch. Ensure you have permission to scan the network.

## Firmware
Arduino IDE 2.x -> Boards Manager -> install `esp32` by Espressif Systems -> select the correct ESP32-S3 board and COM port -> upload `esp32s3_wifi_mapper.ino`. Enable USB CDC On Boot if your S3 board uses native USB serial and serial output is missing. Open Serial Monitor at 115200 to verify `READY` and `DATA` lines; **close Serial Monitor before Python opens the same COM port**.

## Install Python packages
```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Data collection
Mark an outdoor/indoor 10 m x 10 m coordinate grid. Hold the ESP32 at a constant height and orientation. Use 20+ RSSI samples per location, keep router fixed. Record at least 16 train locations and 5-8 **different** test locations distributed across the region (never split repeated samples from the same location between train/test).

```powershell
python collect.py --port COM5 --samples 20 --output measurements.csv
```

At each prompt enter point ID (e.g. P01), x and y in meters, and train/test split. Keep the board still until collection finishes. Scan duration varies by channel and AP count; 20 samples can take longer than 20 seconds.

## Plot and validation
```powershell
python map_and_validate.py --input measurements.csv --width 10 --height 10 --output wifi_heatmap.png
```

Outputs: `wifi_heatmap.png`, `validation_results.csv` if test points exist. Validation prints MAE and RMSE in **dB**, not meters. The heatmap is a model estimate, not a direct RF field measurement. IDW may fail around obstacles and sharp shadowing boundaries; test GPR or propagation-model hybrids later.

## Experimental controls
- Keep router fixed, transmit settings fixed, ESP antenna height and orientation constant.
- Prefer one fixed BSSID and channel; ensure the scan does not mix multiple APs sharing an SSID.
- Avoid standing between ESP and router during measurements.
- Repeat the survey in reverse order to assess temporal drift.
- Record environmental changes (doors, people, obstacles).
- Compare against a nearest-neighbor or constant baseline before claiming model improvement.
- This RSSI mapping experiment **does not detect people**.
