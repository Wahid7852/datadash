import os
import platform
import socket
import struct
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QMessageBox

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
