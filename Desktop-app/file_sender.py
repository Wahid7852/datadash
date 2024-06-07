from PyQt6.QtWidgets import (
    QMessageBox, QWidget, QVBoxLayout, QPushButton, QListWidget, 
    QProgressBar, QLabel, QFileDialog, QApplication, QListWidgetItem
)
from PyQt6.QtGui import QScreen
import os
import socket
import struct
from PyQt6.QtCore import QThread, pyqtSignal
from constant import BROADCAST_ADDRESS, BROADCAST_PORT, LISTEN_PORT

RECEIVER_PORT = 12347

class FileSender(QThread):
    progress_update = pyqtSignal(int)

    def __init__(self, ip_address, file_path):
        super().__init__()
        self.ip_address = ip_address
        self.file_path = file_path

    def run(self):
        file_size = os.path.getsize(self.file_path)
        file_name = os.path.basename(self.file_path)
        file_name_size = len(file_name.encode())
        
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            client_socket.connect((self.ip_address, RECEIVER_PORT))
        except ConnectionRefusedError:
            QMessageBox.critical(None, "Connection Error", "Failed to connect to the specified IP address.")
            return
        
        client_socket.send(struct.pack('<Q', file_name_size))
        client_socket.send(file_name.encode())
        client_socket.send(struct.pack('<Q', file_size))

        sent_size = 0
        with open(self.file_path, 'rb') as f:
            while sent_size < file_size:
                data = f.read(4096)
                client_socket.sendall(data)
                sent_size += len(data)
                self.progress_update.emit(sent_size * 100 // file_size)
        client_socket.close()


class Receiver(QListWidgetItem):
    def __init__(self, name, ip_address):
        super().__init__(f"{name} ({ip_address})")
        self._name = name
        self._ip_address = ip_address
    
    @property
    def name(self):
        return self._name
    
    @name.setter
    def name(self, value):
        self._name = value
        self.updateText()
    
    @property
    def ip_address(self):
        return self._ip_address
    
    @ip_address.setter
    def ip_address(self, value):
        self._ip_address = value
        self.updateText()
    
    def updateText(self):
        self.setText(f"{self._name} ({self._ip_address})")


class SendApp(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()

    def initUI(self):
        self.setWindowTitle('Send File')
        self.setGeometry(100, 100, 400, 300)
        self.center_window()

        layout = QVBoxLayout()

        self.file_button = QPushButton('Select File', self)
        self.file_button.clicked.connect(self.selectFile)
        layout.addWidget(self.file_button)

        self.file_path = None

        self.discover_button = QPushButton('Discover Devices', self)
        self.discover_button.clicked.connect(self.discoverDevices)
        layout.addWidget(self.discover_button)

        self.device_list = QListWidget(self)
        layout.addWidget(self.device_list)

        self.send_button = QPushButton('Send File', self)
        self.send_button.setEnabled(False)
        self.send_button.clicked.connect(self.sendSelectedFile)
        layout.addWidget(self.send_button)

        self.progress_bar = QProgressBar(self)
        layout.addWidget(self.progress_bar)

        self.label = QLabel("", self)
        layout.addWidget(self.label)

        self.setLayout(layout)

    def center_window(self):
        screen = QApplication.primaryScreen()
        screen_geometry = screen.availableGeometry()
        screen_width = screen_geometry.width()
        screen_height = screen_geometry.height()

        window_width = 800
        window_height = 600

        x = (screen_width - window_width) / 2
        y = (screen_height - window_height) / 2

        self.setGeometry(int(x), int(y), window_width, window_height)

    def selectFile(self):
        file_path, _ = QFileDialog.getOpenFileName(self, 'Open File')
        if file_path:
            self.file_path = file_path
            self.checkReadyToSend()

    def discoverDevices(self):
        self.device_list.clear()
        receivers = self.discover_receivers()
        for receiver in receivers:
            item = Receiver(receiver['name'], receiver['ip'])
            self.device_list.addItem(item)
        self.checkReadyToSend()

    def discover_receivers(self):
        receivers = []
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
                        receivers.append({'ip': address[0], 'name': device_name})
            except socket.timeout:
                pass

        return receivers

    def checkReadyToSend(self):
        if self.file_path and self.device_list.count() > 0:
            self.send_button.setEnabled(True)

    def sendSelectedFile(self):
        selected_item = self.device_list.currentItem()
        if not selected_item:
            QMessageBox.critical(None, "Selection Error", "Please select a device to send the file.")
            return
        ip_address = selected_item.ip_address
        self.send_button.setEnabled(False)
        self.file_sender = FileSender(ip_address, self.file_path)
        self.file_sender.progress_update.connect(self.updateProgressBar)
        self.file_sender.start()

    def updateProgressBar(self, value):
        self.progress_bar.setValue(value)
        if value >= 100:
            self.label.setText("File transfer completed!")
