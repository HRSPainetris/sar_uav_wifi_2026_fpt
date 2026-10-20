# CSI Wi-Fi 2,4 GHz — nền tảng nghiên cứu cứu hộ

ESP32-C5 → UDP → PC → chuẩn hóa biên độ → heatmap. Đây là bộ thu đặc trưng vô tuyến, chưa phải bộ phát hiện người, định vị hay tự hành UAV. Firmware cần xác minh biên dịch bằng Arduino core hỗ trợ C5 và thử trên bo thật.

## Firmware Arduino IDE

1. Cài **esp32 by Espressif Systems** có board **ESP32C5 Dev Module**, SDK ESP-IDF 5.5+ và CSI được bật trong build (`CONFIG_ESP_WIFI_CSI_ENABLED`). Core cũ dành cho ESP32/C3 không đủ. Nếu SDK đóng gói chưa bật CSI, cần rebuild Arduino libraries với cấu hình CSI hoặc dùng ESP-IDF; thêm macro trong sketch không bật được tính năng trong thư viện đã biên dịch.
2. Mở `firmware/csi_udp/csi_udp.ino`. Sao chép `secrets.example.h` thành `secrets.h`, điền SSID, mật khẩu và IPv4 LAN của PC. Tệp này được Git bỏ qua.
3. Chọn board/USB/port theo bo thật; Verify, Upload, mở Serial Monitor 115200 baud.
4. Chạy receiver PC, reset bo và xem IP cùng bộ đếm queue drops.

Dùng AP 2,4 GHz, kênh cố định, 20 MHz; tắt band steering, AP/client isolation. Mở UDP inbound 5500 trên firewall PC. C5 kết nối AP để truyền dữ liệu đồng thời bật promiscuous; một radio chỉ nghe kênh hiện tại. Firmware chỉ nhận MAC BSSID của AP và chỉ lấy L-LTF để giảm trộn định dạng. Không trộn nhiều nguồn phát, channel hay LTF khi xử lý.

Tạo downlink tới C5 để có CSI đều: ví dụ Linux `ping -i 0.01 <NODE_IP>` nếu hệ thống cho phép. Không bảo đảm đạt 100 CSI/s; đo tốc độ thực trên receiver. Thí nghiệm nghiêm túc cần bộ phát gói có kiểm soát. Đường sensing là AP→C5; UDP uplink dùng chung airtime nên gây jitter/mất mẫu. Promiscuous không tự tạo gói phát.

Callback chỉ copy vào queue 16 frame; gửi UDP ở `loop()`. Không in Serial hay gửi mạng trong callback. Datagram tối đa 1054 byte để tránh phân mảnh trên LAN MTU 1500. Chưa có tự reconnect: reset bo khi Wi-Fi mất kết nối; restart receiver khi bo reset để tạo phiên mới. Cổng UDP node là 5501, PC là 5500. Đổi node ID trong sketch nếu dùng nhiều bo.

Bản mẫu chỉ stream UDP, chưa có TCP điều khiển. Khi thêm start/stop, đổi cấu hình, dùng TCP có framing, ID lệnh và ACK ứng dụng.

## Chạy PC

Python 3.10+; máy desktop cần backend GUI Matplotlib.

```bash
cd /workspace/sar_uav_wifi_2026_fpt
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python pc/csi.py receive --node 1 --fps 30 --history 400
```

Windows: tạo venv bằng `py -m venv .venv`, dùng `.venv\Scripts\python.exe` và `python -m pip` thay đường dẫn Linux.

Không có bo: chạy simulator ở terminal thứ hai:

```bash
.venv/bin/python pc/csi.py simulate --rate 100 --seconds 20
```

Cloud/headless: receiver có thể lưu PNG; chạy simulator trong terminal khác trong lúc receiver đang nghe.

```bash
MPLBACKEND=Agg .venv/bin/python pc/csi.py receive --seconds 8 --headless /tmp/csi.png
# terminal khác:
.venv/bin/python pc/csi.py simulate --seconds 5
# kiểm thử DSP/giao thức:
.venv/bin/python -m unittest discover -s tests -v
```

GUI mục tiêu 30 FPS, mỗi lần cập nhật nhận nhiều gói. FPS khác tốc độ lấy mẫu CSI. Giữ 400 gói gần nhất; trục ngang là thứ tự gói, tiêu đề có khoảng thời gian thật và tốc độ đo bằng timestamp node. Trục chưa phải thời gian đều khi mất gói.

Receiver khóa vào link đầu tiên phù hợp `--node`: IP node, ID, MAC phát, kênh và chiều dài CSI; link khác được đếm ignored. Dùng tiến trình/cổng riêng cho từng node trong bản mẫu. Gói trùng/đảo thứ tự bị bỏ. `missing` là khoảng trống sequence sau điểm cấp số; không phân biệt queue drop và mất UDP. Chưa có ghi phiên dữ liệu thô hoặc đồng bộ nhiều node.

## Giao thức v1

Header 30 byte little endian (Python struct `<4sBBHIQ6sbBH`), tiếp theo int8 CSI:

| Trường | Kiểu | Ý nghĩa |
|---|---|---|
| magic/version | 4 byte / uint8 | CSI1 / 1 |
| flags | uint8 | bit 0: bốn byte CSI đầu không hợp lệ |
| node | uint16 | ID cấu hình trong sketch |
| sequence | uint32 | tăng theo gói được chọn, có wrap |
| timestamp | uint64 | microsecond esp_timer_get_time tại callback |
| MAC | 6 byte | nguồn phát |
| RSSI/channel | int8 / uint8 | dBm / kênh |
| length | uint16 | byte CSI, chẵn, tối đa 1024 |
| CSI | int8 pairs | **imaginary, real**, H = real + j imaginary |

Không gửi native struct SDK. Timestamp là đồng hồ riêng node có jitter callback, không đồng bộ giữa các node. PC đánh dấu vị trí invalid bằng NaN, không xóa làm lệch chỉ số. Null/guard/DC và thứ tự subcarrier phải tra theo C5/SDK/PHY/LTF thực tế. Chiều dài bằng nhau chưa đủ chứng minh hai PHY layout giống nhau. Heatmap hiện là **chỉ số CSI thô**, chưa ánh xạ tần số subcarrier vật lý và chưa là bản đồ không gian.

## DSP, Nyquist, Fourier, STFT

Với k là subcarrier, n là gói: H[k,n] = I + jQ; A = |H|, φ = angle(H).

PC tính 20 log10(A), trừ median theo gói để giảm gain chung như AGC, clip và EMA theo thời gian. Cách này có thể loại cả biến thiên hữu ích; cutoff EMA theo gói thay đổi khi tốc độ gói thay đổi. Không thể khẳng định normalization loại hết sai lệch phần cứng, đồng hồ hoặc biến động môi trường. So sánh với dữ liệu thô và baseline phòng trống; tránh lọc quá mạnh trước phân tích Doppler.

`sanitize_phase(csi, subcarrier_indices)` unwrap và loại xu thế affine theo chỉ số subcarrier **vật lý tăng dần trong một LTF**, sau khi bỏ nulls. Không gọi trực tiếp trên buffer thô chưa mapping. Nó giảm một phần offset/slope do CFO/SFO/packet detection delay; không khôi phục pha tuyệt đối, có thể xóa thông tin đường truyền và không đồng bộ các node. Pha gần biên độ 0 không đáng tin; CSI ratio/differential cần phần cứng/link đồng bộ phù hợp.

Có hai miền lấy mẫu:

- Sóng 2,4 GHz được radio hạ tần và xử lý OFDM; PC không cần lấy CSI ở trên 4,8 GHz.
- CSI theo thời gian lấy mẫu theo **gói hợp lệ**, ví dụ 100 Hz. Muốn đo biến thiên đến 20 Hz thì Nyquist yêu cầu >40 mẫu/s đều; thực tế nên dư địa, ví dụ 100–200 Hz, theo dõi jitter/mất gói và chống alias trước giảm mẫu. FPS GUI không phải sample rate.

FFT phân tích tần số biến thiên của chuỗi theo thời gian. STFT dùng cửa sổ trượt rồi FFT, tạo spectrogram thời gian–tần số. `doppler_spectrogram(t, x, fs=100, window=128)` nhận một đặc trưng vô hướng của một bin/link đã chọn; kiểm tra timestamp, từ chối gap lớn, nội suy sang lưới đều, detrend rồi STFT Hann. Nội suy không tạo thông tin và không thay bộ lọc chống alias. Với fs=100 Hz, N=128: cửa sổ 1,28 s, khoảng bin 0,78125 Hz, hop 32 mẫu = 0,32 s. Thay N đánh đổi độ phân giải thời gian/tần số. Chia segment thay vì nội suy qua mất dữ liệu dài; chỉnh max_gap theo băng tần mục tiêu.

Heatmap thời gian–CSI index khác spectrogram. Khoảng subcarrier legacy 20 MHz là 312,5 kHz; HE có numerology khác. Doppler lưỡng tĩnh phụ thuộc hình học AP–người–C5 nên không chuyển một đỉnh spectrogram thành tốc độ/vị trí duy nhất.

`gaussian_augment()` thêm Gaussian noise có seed cho đặc trưng chuẩn hóa của **tập train**, là regularization chứ không phải bộ lọc đo. Chia train/validation/test theo người, phòng và phiên trước khi fit normalization/augmentation. Không chia ngẫu nhiên các cửa sổ chồng lấn cùng phiên để tránh rò rỉ dữ liệu.

## Lộ trình UAV/cứu hộ

1. TX/RX tĩnh: thu phòng trống, đứng yên, đi lại, nhiều người, quạt/vật chuyển động. Ghi nhãn độc lập có đồng thuận; lưu dữ liệu thô, cấu hình PHY, timestamp, mất gói, bối cảnh. Receiver hiện chưa ghi phiên đo.
2. Đánh giá baseline biên độ/năng lượng STFT trước CNN/GRU. Báo precision, recall, false alarms, độ trễ; kiểm tra phòng/người chưa thấy. Người đứng yên hoặc che khuất có thể không phát hiện được.
3. Nhiều liên kết với tọa độ và thời gian đã hiệu chuẩn: fingerprint hoặc radio tomographic imaging cần mô hình và kiểm chứng độ phân giải. Một anten/link không đủ xác định duy nhất vị trí người; nhiều node không tự biến thành radar.
4. Sau baseline tĩnh mới thử UAV. Chuyển động, rotation, rung, cánh quạt và antenna có thể lấn át tín hiệu người. Cần IMU/odometry, pose và bù chuyển động. Không dùng bản mẫu làm tín hiệu an toàn điều khiển UAV.

## Nguồn nghiên cứu

- [Espressif ESP-CSI](https://github.com/espressif/esp-csi): ví dụ thu và sensing.
- [ESP-IDF C5 CSI](https://docs.espressif.com/projects/esp-idf/en/stable/esp32c5/api-guides/wifi.html#wi-fi-channel-state-information): callback, layout, hạn chế.
- [Header HE CSI v5.5](https://github.com/espressif/esp-idf/blob/v5.5/components/esp_wifi/include/esp_wifi_he_types.h): API C5 dùng trong sketch.
- [Arduino ESP32](https://github.com/espressif/arduino-esp32): chọn và khóa phiên bản đã kiểm thử trên bo.
- [SciPy STFT](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.stft.html): window, overlap, scaling.
- *Widar3.0: Zero-Effort Cross-Domain Gesture Recognition With Wi-Fi* (MobiSys 2019): Doppler và tổng quát hóa giữa miền; không chứng minh định vị cứu hộ bằng một C5.
- *Through-Wall Human Pose Estimation Using Radio Signals* (RF-Pose, CVPR 2018): RF pose dùng phần cứng RF chuyên dụng, không chuyển trực tiếp sang CSI ESP32.
