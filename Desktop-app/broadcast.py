import sys
import json
import platform
import socket
import struct
import math
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QMessageBox, QListWidget, QListWidgetItem, QFrame
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QPointF, QTimer, QSize
from PyQt6.QtGui import QScreen, QColor, QLinearGradient, QPainter, QPen, QFont, QIcon
from constant import BROADCAST_ADDRESS, BROADCAST_PORT, LISTEN_PORT, logger
from file_sender import SendApp
from file_sender_java import SendAppJava

SENDER_JSON = 53000
RECEIVER_JSON = 54000

class CircularDeviceButton(QPushButton):
    def __init__(self, device_name, device_ip, parent=None):
        super().__init__(device_name[0], parent)
        self.device_name = device_name
        self.device_ip = device_ip
        self.setFixedSize(60, 60)  # Increased size for better visibility
        self.setStyleSheet("""
            QPushButton {
                background-color: #4a90e2;
                color: white;
                border-radius: 30px;
                font-weight: bold;
                font-size: 18px;
            }
            QPushButton:hover {
                background-color: #357abd;
            }
        """)

class BroadcastWorker(QThread):
    device_detected = pyqtSignal(dict)
    device_connected = pyqtSignal(str, str, dict)
    device_connected_java = pyqtSignal(str, str, dict)

    def __init__(self):
        super().__init__()
        self.socket = None
        self.client_socket = None
        self.receiver_data = None

    def run(self):
        self.discover_receivers()

    def discover_receivers(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(('', LISTEN_PORT))

            s.sendto(b'DISCOVER', (BROADCAST_ADDRESS, BROADCAST_PORT))

            s.settimeout(2)
            try:
                while True:
                    message, address = s.recvfrom(1024)
                    message = message.decode()
                    if message.startswith('RECEIVER:'):
                        device_name = message.split(':')[1]
                        self.device_detected.emit({'ip': address[0], 'name': device_name})
            except socket.timeout:
                pass

    def connect_to_device(self, device_ip, device_name):
        try:
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client_socket.bind(('', SENDER_JSON))
            self.client_socket.connect((device_ip, RECEIVER_JSON))

            device_data = {
                'device_type': 'python',
                'os': platform.system()
            }
            device_data_json = json.dumps(device_data)
            self.client_socket.send(struct.pack('<Q', len(device_data_json)))
            self.client_socket.send(device_data_json.encode())

            receiver_json_size = struct.unpack('<Q', self.client_socket.recv(8))[0]
            receiver_json = self.client_socket.recv(receiver_json_size).decode()
            self.receiver_data = json.loads(receiver_json)

            device_type = self.receiver_data.get('device_type', 'unknown')
            if device_type == 'python':
                self.device_connected.emit(device_ip, device_name, self.receiver_data)
            elif device_type == 'java':
                self.device_connected_java.emit(device_ip, device_name, self.receiver_data)
            else:
                raise ValueError("Unsupported device type")

        except Exception as e:
            QMessageBox.critical(None, "Connection Error", f"Failed to connect: {str(e)}")
        finally:
            if self.client_socket:
                self.client_socket.close()

class Broadcast(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Device Discovery')
        self.setFixedSize(1280, 720)  # Updated to 1280x720 (16:9 ratio)
        self.center_window()

        self.devices = []
        self.broadcast_worker = BroadcastWorker()
        self.broadcast_worker.device_detected.connect(self.add_device)
        self.broadcast_worker.device_connected.connect(self.show_send_app)
        self.broadcast_worker.device_connected_java.connect(self.show_send_app_java)

        self.animation_offset = 0
        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(self.update_animation)
        self.animation_timer.start(50)  # Update every 50ms

        self.initUI()

    def initUI(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setFixedHeight(70)
        header.setStyleSheet("background-color: #333; padding: 0px;")
        header_layout = QHBoxLayout(header)

        title_label = QLabel("Device Discovery")
        title_label.setFont(QFont("Arial", 24, QFont.Weight.Bold))
        title_label.setStyleSheet("color: white;")
        header_layout.addWidget(title_label, alignment=Qt.AlignmentFlag.AlignCenter)

        main_layout.addWidget(header)

        # Main content area
        content = QWidget()
        content_layout = QVBoxLayout(content)
        
        # Circular device display
        self.device_area = QWidget()
        self.device_area.setFixedSize(600, 600)  # Increased size for larger window
        content_layout.addWidget(self.device_area, alignment=Qt.AlignmentFlag.AlignCenter)

        # Refresh button
        self.refresh_button = QPushButton('Refresh')
        self.style_button(self.refresh_button)
        self.refresh_button.clicked.connect(self.discover_devices)
        content_layout.addWidget(self.refresh_button, alignment=Qt.AlignmentFlag.AlignCenter)

        main_layout.addWidget(content)
        self.setLayout(main_layout)

    def style_button(self, button):
        button.setFixedSize(180, 60)  # Increased size for better visibility
        button.setFont(QFont("Arial", 18))
        button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 rgba(47, 54, 66, 255),
                    stop: 1 rgba(75, 85, 98, 255)
                );
                color: white;
                border-radius: 30px;
                border: 1px solid rgba(0, 0, 0, 0.5);
                padding: 8px;
                font-weight: bold;
                font-size: 18px;
            }
            QPushButton:hover {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 rgba(60, 68, 80, 255),
                    stop: 1 rgba(90, 100, 118, 255)
                );
            }
            QPushButton:pressed {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 rgba(35, 41, 51, 255),
                    stop: 1 rgba(65, 75, 88, 255)
                );
            }
        """)

    def center_window(self):
        screen = QScreen.availableGeometry(QApplication.primaryScreen())
        window_width, window_height = 1280, 720
        x = (screen.width() - window_width) // 2
        y = (screen.height() - window_height) // 2
        self.setGeometry(x, y, window_width, window_height)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw background gradient
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0, QColor('#b0b0b0'))
        gradient.setColorAt(1, QColor('#505050'))
        painter.fillRect(self.rect(), gradient)

        # Draw animated circular rings
        painter.setPen(QPen(Qt.GlobalColor.white, 3))  # Increased line width
        center = QPointF(self.width() / 2, self.height() / 2)
        for i in range(4):
            radius = 250 - i * 50  # Increased size for larger window
            painter.drawEllipse(center, radius + self.animation_offset, radius + self.animation_offset)

    def update_animation(self):
        self.animation_offset += 1
        if self.animation_offset > 50:  # Adjusted for larger animation
            self.animation_offset = 0
        self.update()

    def discover_devices(self):
        self.devices.clear()
        for child in self.device_area.children():
            if isinstance(child, CircularDeviceButton):
                child.deleteLater()
        self.broadcast_worker.start()

    def add_device(self, device_info):
        self.devices.append(device_info)
        self.update_devices()

    def update_devices(self):
        for child in self.device_area.children():
            if isinstance(child, CircularDeviceButton):
                child.deleteLater()

        for i, device in enumerate(self.devices):
            angle = i * (2 * math.pi / len(self.devices))
            x = 300 + 250 * math.cos(angle) - 30  # Adjusted for larger CircularDeviceButton
            y = 300 + 250 * math.sin(angle) - 30  # Adjusted for larger CircularDeviceButton
            button = CircularDeviceButton(device['name'], device['ip'], self.device_area)
            button.move(int(x), int(y))
            button.clicked.connect(lambda checked, d=device: self.connect_to_device(d))
            button.show()

    def connect_to_device(self, device):
        confirm_dialog = QMessageBox(self)
        confirm_dialog.setWindowTitle("Confirm Connection")
        confirm_dialog.setText(f"Connect to {device['name']}?")
        confirm_dialog.setIcon(QMessageBox.Icon.Question)

        # Add buttons
        yes_button = confirm_dialog.addButton("Yes", QMessageBox.ButtonRole.YesRole)
        no_button = confirm_dialog.addButton("No", QMessageBox.ButtonRole.NoRole)

        # Apply consistent styling
        confirm_dialog.setStyleSheet("""
            QMessageBox {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 1,
                    stop: 0 #b0b0b0,
                    stop: 1 #505050
                );
                color: #FFFFFF;
                font-size: 18px;
            }
            QLabel {
                background-color: transparent;
                font-size: 18px;
            }
            QPushButton {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 rgba(47, 54, 66, 255),
                    stop: 1 rgba(75, 85, 98, 255)
                );
                color: white;
                border-radius: 15px;
                border: 1px solid rgba(0, 0, 0, 0.5);
                padding: 8px;
                font-size: 18px;
            }
            QPushButton:hover {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 rgba(60, 68, 80, 255),
                    stop: 1 rgba(90, 100, 118, 255)
                );
            }
            QPushButton:pressed {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 rgba(35, 41, 51, 255),
                    stop: 1 rgba(65, 75, 88, 255)
                );
            }
        """)

        confirm_dialog.exec()

        if confirm_dialog.clickedButton() == yes_button:
            self.broadcast_worker.connect_to_device(device['ip'], device['name'])

    def show_send_app(self, device_ip, device_name, receiver_data):
        self.hide()
        self.send_app = SendApp(device_ip, device_name, receiver_data)
        self.send_app.show()

    def show_send_app_java(self, device_ip, device_name, receiver_data):
        self.hide()
        self.send_app_java = SendAppJava(device_ip, device_name, receiver_data)
        self.send_app_java.show()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    broadcast_app = Broadcast()
    broadcast_app.show()
    sys.exit(app.exec())    