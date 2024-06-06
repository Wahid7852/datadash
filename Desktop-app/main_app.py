import socket
import threading
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QListWidget, QProgressBar, QLabel, QFileDialog, QMessageBox
from PyQt6.QtCore import pyqtSignal
from file_receiver import FileReceiver
from file_sender import FileSender
from constant import BROADCAST_ADDRESS, BROADCAST_PORT, LISTEN_PORT

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
