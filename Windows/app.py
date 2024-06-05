import sys
import os
import platform
import socket
import struct
import threading
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *

# Constants
BROADCAST_PORT = 12345
BROADCAST_ADDRESS = '<broadcast>'
LISTEN_PORT = 12346
RECEIVER_PORT = 12347

DEVICE_NAME = "PythonDevice"

class FileReceiver(QThread):
    progress_update = pyqtSignal(int)

    def __init__(self):
        super().__init__()

    def run(self):
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.bind(('0.0.0.0', RECEIVER_PORT))
        server_socket.listen(1)
        client_socket, addr = server_socket.accept()
        with client_socket:
            file_name_size = struct.unpack('<Q', client_socket.recv(8))[0]
            file_name = client_socket.recv(file_name_size).decode()
            file_size = struct.unpack('<Q', client_socket.recv(8))[0]
            received_size = 0

            # Determine the file path based on the OS
            if platform.system() == 'Windows':
                os.makedirs("c:\\Received", exist_ok=True)
                file_path = os.path.join("c:\\Received", file_name)
            elif platform.system() == 'Linux':
                home_dir = os.path.expanduser('~')
                os.makedirs(os.path.join(home_dir, "received"), exist_ok=True)
                file_path = os.path.join(home_dir, "received", file_name)
            elif platform.system() == 'Darwin':
                home_dir = os.path.expanduser('~')
                documents_dir = os.path.join(home_dir, "Documents")
                os.makedirs(os.path.join(documents_dir, "received"), exist_ok=True)
                file_path = os.path.join(documents_dir, "received", file_name)
            else:
                QMessageBox.critical(None, "Unsupported OS", "This OS is not supported.")
                return

            with open(file_path, "wb") as f:
                while received_size < file_size:
                    data = client_socket.recv(4096)
                    if not data:
                        break
                    f.write(data)
                    received_size += len(data)
                    self.progress_update.emit(received_size * 100 // file_size)
        server_socket.close()

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


class MainApp(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()

    def initUI(self):
        self.setWindowTitle('Media Sharing App')
        self.setGeometry(100, 100, 300, 200)

        layout = QVBoxLayout()

        self.send_button = QPushButton('Send File', self)
        self.send_button.clicked.connect(self.sendFile)
        layout.addWidget(self.send_button)

        self.receive_button = QPushButton('Receive File', self)
        self.receive_button.clicked.connect(self.receiveFile)
        layout.addWidget(self.receive_button)

        self.setLayout(layout)

    def sendFile(self):
        self.hide()
        self.send_app = SendApp()
        self.send_app.show()

    def receiveFile(self):
        self.hide()
        self.receive_app = ReceiveApp()
        self.receive_app.show()

class SendApp(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()

    def initUI(self):
        self.setWindowTitle('Send File')
        self.setGeometry(100, 100, 400, 300)

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

    def selectFile(self):
        file_path, _ = QFileDialog.getOpenFileName(self, 'Open File')
        if file_path:
            self.file_path = file_path
            self.checkReadyToSend()

    def discoverDevices(self):
        self.device_list.clear()
        receivers = self.discover_receivers()
        for receiver in receivers:
            self.device_list.addItem(f"{receiver['name']} ({receiver['ip']})")
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
        ip_address = selected_item.text().split('(')[-1][:-1]
        self.send_button.setEnabled(False)
        self.file_sender = FileSender(ip_address, self.file_path)
        self.file_sender.progress_update.connect(self.updateProgressBar)
        self.file_sender.start()

    def updateProgressBar(self, value):
        self.progress_bar.setValue(value)
        if value >= 100:
            self.label.setText("File transfer completed!")

class ReceiveApp(QWidget):
    progress_update = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.initUI()

    def initUI(self):
        self.setWindowTitle('Receive File')
        self.setGeometry(100, 100, 300, 200)

        layout = QVBoxLayout()

        self.label = QLabel("Waiting for file...", self)
        layout.addWidget(self.label)

        self.progress_bar = QProgressBar(self)
        layout.addWidget(self.progress_bar)

        self.setLayout(layout)

        self.file_receiver = FileReceiver()
        self.file_receiver.progress_update.connect(self.updateProgressBar)
        self.file_receiver.start()

        threading.Thread(target=self.listenForBroadcast, daemon=True).start()

    def listenForBroadcast(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.bind(('', BROADCAST_PORT))
            while True:
                message, address = s.recvfrom(1024)
                if message.decode() == 'DISCOVER':
                    response = f"RECEIVER:{DEVICE_NAME}"
                    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as response_socket:
                        response_socket.sendto(response.encode(), (address[0], LISTEN_PORT))

    def updateProgressBar(self, value):
        self.progress_bar.setValue(value)
        if value >= 100:
            self.label.setText("File transfer completed!")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    main_app = MainApp()
    main_app.show()
    sys.exit(app.exec())
