import sys
import time
from PyQt5.QtWidgets import QApplication, QMainWindow, QLabel, QVBoxLayout, QHBoxLayout, QWidget, QPushButton
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QTimer
from pymavlink import mavutil

# --- AYARLAR ---
FIRMWARE_IP = '127.0.0.1'
RC_PORT = 14553        # Komut göndereceğimiz port
TELEMETRY_PORT = 14552 # Veri dinleyeceğimiz port

# --- HABERLEŞME İŞÇİSİ (TELEMETRİ ALICISI) ---
class MavlinkReceiver(QThread):
    data_received = pyqtSignal(str)
    attitude_received = pyqtSignal(float, float, float)
    heartbeat_received = pyqtSignal(str) # Mod bilgisini buradan alacağız

    def run(self):
        connection_string = f'udpin:0.0.0.0:{TELEMETRY_PORT}'
        self.data_received.emit(f"Telemetri Bekleniyor: {connection_string}...")
        
        try:
            master = mavutil.mavlink_connection(connection_string)
        except Exception as e:
            self.data_received.emit(f"HATA: {e}")
            return

        while True:
            msg = master.recv_match(blocking=False)
            if not msg:
                time.sleep(0.01)
                continue

            msg_type = msg.get_type()
            
            if msg_type == 'HEARTBEAT':
                # Firmware hangi modda olduğunu Heartbeat içindeki custom_mode ile söyler
                # 0: Stabilize, 3: Loiter, 6: RTL
                mode_id = msg.custom_mode
                mode_str = "BİLİNMİYOR"
                if mode_id == 0: mode_str = "STABILIZE"
                elif mode_id == 3: mode_str = "LOITER"
                elif mode_id == 6: mode_str = "RTL"
                
                self.heartbeat_received.emit(mode_str)
            
            elif msg_type == 'ATTITUDE':
                roll = msg.roll * 57.2958
                pitch = msg.pitch * 57.2958
                yaw = msg.yaw * 57.2958
                self.attitude_received.emit(roll, pitch, yaw)

# --- ANA PENCERE (KUMANDA MERKEZİ) ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("AthenaGCS - Taktik Komuta Merkezi")
        self.setGeometry(100, 100, 800, 600)

        # -- RC DEĞERLERİ --
        # 8 Kanal: [Roll, Pitch, Thr, Yaw, MOD, Aux1, Aux2, Aux3]
        # Mod Kanalı (Index 4) Varsayılan 1000 (Stabilize)
        self.rc_channels = [1500, 1500, 1000, 1500, 1000, 0, 0, 0] 
        self.keys_pressed = set() 

        # -- GÖNDERİCİ --
        self.mav_sender = mavutil.mavlink_connection(f'udpout:{FIRMWARE_IP}:{RC_PORT}', source_system=255)

        # -- ARAYÜZ TASARIMI --
        layout = QVBoxLayout()

        # 1. Başlık ve Aktif Mod
        header_layout = QHBoxLayout()
        self.label_title = QLabel("ATHENA PILOT")
        self.label_title.setStyleSheet("font-size: 24px; font-weight: bold; color: #2c3e50;")
        
        self.label_mode = QLabel("MOD: BEKLENİYOR")
        self.label_mode.setStyleSheet("font-size: 20px; font-weight: bold; color: #e74c3c; border: 2px solid #bdc3c7; padding: 5px;")
        
        header_layout.addWidget(self.label_title)
        header_layout.addStretch()
        header_layout.addWidget(self.label_mode)
        layout.addLayout(header_layout)

        # 2. Telemetri Paneli
        self.label_attitude = QLabel("Roll: --  |  Pitch: --  |  Yaw: --")
        self.label_attitude.setAlignment(Qt.AlignCenter)
        self.label_attitude.setStyleSheet("font-size: 24px; background-color: #34495e; color: white; padding: 20px; border-radius: 10px;")
        layout.addWidget(self.label_attitude)

        # 3. MOD SEÇİM BUTONLARI (YENİ)
        mode_layout = QHBoxLayout()
        
        self.btn_stab = QPushButton("STABILIZE (Manuel)")
        self.btn_stab.setCheckable(True)
        self.btn_stab.clicked.connect(lambda: self.set_flight_mode(1000))
        self.style_button(self.btn_stab, "#2ecc71") # Yeşil

        self.btn_loiter = QPushButton("LOITER (GPS)")
        self.btn_loiter.setCheckable(True)
        self.btn_loiter.clicked.connect(lambda: self.set_flight_mode(1500))
        self.style_button(self.btn_loiter, "#f39c12") # Turuncu

        self.btn_rtl = QPushButton("RTL (Eve Dön)")
        self.btn_rtl.setCheckable(True)
        self.btn_rtl.clicked.connect(lambda: self.set_flight_mode(2000))
        self.style_button(self.btn_rtl, "#e74c3c") # Kırmızı

        mode_layout.addWidget(self.btn_stab)
        mode_layout.addWidget(self.btn_loiter)
        mode_layout.addWidget(self.btn_rtl)
        layout.addLayout(mode_layout)

        # 4. RC Durum ve Bilgi
        self.label_rc = QLabel("RC OUT: [ -- ]")
        self.label_rc.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label_rc)

        self.label_log = QLabel("Sistem Hazır...")
        self.label_log.setAlignment(Qt.AlignCenter)
        self.label_log.setStyleSheet("color: gray;")
        layout.addWidget(self.label_log)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        # -- THREAD VE ZAMANLAYICI --
        self.worker = MavlinkReceiver()
        self.worker.data_received.connect(self.update_log)
        self.worker.attitude_received.connect(self.update_attitude)
        self.worker.heartbeat_received.connect(self.update_mode_display)
        self.worker.start()

        self.timer = QTimer()
        self.timer.timeout.connect(self.send_rc_loop)
        self.timer.start(50) 

    # --- BUTON VE STİL İŞLEMLERİ ---
    def style_button(self, btn, color):
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #95a5a6; color: white; font-size: 16px; padding: 15px; border-radius: 5px; font-weight: bold;
            }}
            QPushButton:checked {{
                background-color: {color}; border: 3px solid #2c3e50;
            }}
        """)

    def set_flight_mode(self, pwm):
        # Kanal 5 değerini güncelle
        self.rc_channels[4] = pwm
        
        # Butonların görsel durumunu güncelle (Sadece biri basılı kalsın)
        self.btn_stab.setChecked(pwm == 1000)
        self.btn_loiter.setChecked(pwm == 1500)
        self.btn_rtl.setChecked(pwm == 2000)
        
        mode_name = "STABILIZE" if pwm == 1000 else "LOITER" if pwm == 1500 else "RTL"
        self.update_log(f"Mod Komutu Gönderildi: {mode_name}")

    # --- KLAVYE ---
    def keyPressEvent(self, event):
        self.keys_pressed.add(event.key())

    def keyReleaseEvent(self, event):
        if event.key() in self.keys_pressed:
            self.keys_pressed.remove(event.key())

    # --- DÖNGÜ ---
    def send_rc_loop(self):
        # Roll (A/D)
        if Qt.Key_A in self.keys_pressed: self.rc_channels[0] = 1300
        elif Qt.Key_D in self.keys_pressed: self.rc_channels[0] = 1700
        else: self.rc_channels[0] = 1500

        # Pitch (W/S)
        if Qt.Key_W in self.keys_pressed: self.rc_channels[1] = 1300
        elif Qt.Key_S in self.keys_pressed: self.rc_channels[1] = 1700
        else: self.rc_channels[1] = 1500

        # Throttle (Oklar)
        if Qt.Key_I in self.keys_pressed: 
            self.rc_channels[2] += 20  # Biraz daha hızlı artsın
            print(f"Gaz Artıyor: {self.rc_channels[2]}") # Terminalde görelim
        if Qt.Key_K in self.keys_pressed: 
            self.rc_channels[2] -= 20
            print(f"Gaz Azalıyor: {self.rc_channels[2]}")

        # Ekrana Yaz
        self.label_rc.setText(f"Roll:{self.rc_channels[0]} | Pit:{self.rc_channels[1]} | Thr:{self.rc_channels[2]} | MOD:{self.rc_channels[4]}")

        # Gönder (Kanal 5 Dahil!)
        self.mav_sender.mav.rc_channels_override_send(
            1, 1,
            self.rc_channels[0], self.rc_channels[1], self.rc_channels[2], self.rc_channels[3],
            self.rc_channels[4], # MOD KANALI
            0, 0, 0
        )

    def update_log(self, message):
        self.label_log.setText(message)

    def update_attitude(self, roll, pitch, yaw):
        self.label_attitude.setText(f"Roll: {roll:.1f}°  |  Pitch: {pitch:.1f}°  |  Yaw: {yaw:.1f}°")

    def update_mode_display(self, mode_str):
        # Firmware'den gelen gerçek modu göster
        self.label_mode.setText(f"AKTİF MOD: {mode_str}")
        if mode_str == "RTL": self.label_mode.setStyleSheet("font-size: 20px; font-weight: bold; color: white; background-color: #e74c3c; padding: 5px;")
        elif mode_str == "LOITER": self.label_mode.setStyleSheet("font-size: 20px; font-weight: bold; color: white; background-color: #f39c12; padding: 5px;")
        else: self.label_mode.setStyleSheet("font-size: 20px; font-weight: bold; color: white; background-color: #2ecc71; padding: 5px;")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())