import os
import socket
import struct
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QMessageBox

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
