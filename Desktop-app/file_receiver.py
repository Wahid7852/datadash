import os
import platform
import socket
import struct
import threading
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QMessageBox, QWidget, QVBoxLayout, QLabel, QProgressBar, QApplication
)
from constant import BROADCAST_ADDRESS, BROADCAST_PORT, LISTEN_PORT

RECEIVER_PORT = 12347

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
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(('', BROADCAST_PORT))

            while True:
                message, address = s.recvfrom(1024)
                message = message.decode()
                if message == 'DISCOVER':
                    response = f'RECEIVER:{socket.gethostname()}'
                    s.sendto(response.encode(), address)

    def updateProgressBar(self, value):
        self.progress_bar.setValue(value)
        if value >= 100:
            self.label.setText("File received successfully!")
