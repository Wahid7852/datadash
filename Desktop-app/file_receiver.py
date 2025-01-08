import os
import platform
import socket
import struct
import threading
import json
from time import sleep
import subprocess
import shutil
from PyQt6.QtCore import QThread, pyqtSignal, QTimer, Qt, QMetaObject
from PyQt6 import QtCore
from PyQt6.QtWidgets import (
    QMessageBox, QWidget, QVBoxLayout, QLabel, QProgressBar, 
    QApplication, QHBoxLayout, QPushButton
)
from PyQt6.QtGui import QScreen, QMovie, QKeySequence, QKeyEvent, QFont
from constant import (
    BROADCAST_PORT, LISTEN_PORT, get_config, logger, 
    RECEIVER_JSON, RECEIVER_DATA, SENDER_DATA
)
from crypt_handler import decrypt_file, Decryptor

class BaseReceiveWorker(QThread):
    progress_update = pyqtSignal(int)
    decrypt_signal = pyqtSignal(list)
    receiving_started = pyqtSignal()
    transfer_finished = pyqtSignal()
    error_occurred = pyqtSignal(str, str, str)
    password = None

    def __init__(self, client_ip):
        super().__init__()
        self.client_skt = None
        self.server_skt = None
        self.encrypted_files = []
        self.broadcasting = True
        self.metadata = None
        self.destination_folder = None
        self.store_client_ip = client_ip
        self.base_folder_name = ''
        logger.debug(f"Client IP address stored: {self.store_client_ip}")

    def initialize_connection(self):
        try:
            if self.server_skt:
                try:
                    self.server_skt.shutdown(socket.SHUT_RDWR)
                    self.server_skt.close()
                except:
                    pass
                
            self.server_skt = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_skt.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            if platform.system() != 'Windows':
                try:
                    self.server_skt.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except AttributeError:
                    logger.debug("SO_REUSEPORT not available on this platform")
            
            self.server_skt.settimeout(60)
            self.server_skt.bind(('', RECEIVER_DATA))
            self.server_skt.listen(1)
            logger.debug("Server initialized on port %d", RECEIVER_DATA)
            
        except OSError as e:
            if e.errno == 48:
                logger.error("Port %d is in use, waiting to retry...", RECEIVER_DATA)
                sleep(1)
                self.initialize_connection()
            else:
                raise
        except Exception as e:
            logger.error("Failed to initialize server: %s", str(e))
            raise

    def accept_connection(self):
        if self.client_skt:
            self.client_skt.close()
        try:
            self.client_skt, self.client_address = self.server_skt.accept()
            print(f"Connected to {self.client_address}")
        except Exception as e:
            error_message = f"Failed to accept connection: {str(e)}"
            logger.error(error_message)
            self.error_occurred.emit("Connection Error", error_message, "")
            return None

    def run(self):
        self.initialize_connection()
        self.accept_connection()
        if self.client_skt:
            self.receiving_started.emit()
            self.receive_files()
        else:
            logger.error("Failed to establish a connection.")

        if self.client_skt:
            self.client_skt.close()
        if self.server_skt:
            self.server_skt.close()

    def receive_files(self):
        self.broadcasting = False
        logger.debug("File reception started.")
        is_folder_transfer = False

        while True:
            try:
                encryption_flag = self.client_skt.recv(8).decode()
                logger.debug("Received encryption flag: %s", encryption_flag)

                if not encryption_flag:
                    logger.debug("Dropped redundant data: %s", encryption_flag)
                    break

                if encryption_flag[-1] == 't':
                    encrypted_transfer = True
                elif encryption_flag[-1] == 'h':
                    if self.encrypted_files:
                        self.decrypt_signal.emit(self.encrypted_files)
                    self.encrypted_files = []
                    logger.debug("Received halt signal. Stopping file reception.")
                    self.transfer_finished.emit()
                    break
                else:
                    encrypted_transfer = False

                file_name_size_data = self.client_skt.recv(8)
                file_name_size = struct.unpack('<Q', file_name_size_data)[0]
                logger.debug("File name size received: %d", file_name_size)
                
                if file_name_size == 0:
                    logger.debug("End of transfer signal received.")
                    break

                file_name = self._receive_data(self.client_skt, file_name_size).decode()
                file_name = file_name.replace('\\', '/')
                logger.debug("Original file name: %s", file_name)

                file_size_data = self.client_skt.recv(8)
                file_size = struct.unpack('<Q', file_size_data)[0]

                try:
                    if file_name == 'metadata.json':
                        logger.debug("Receiving metadata file.")
                        self.metadata = self.receive_metadata(file_size)
                        is_folder_transfer = any(file_info.get('path', '').endswith('/') 
                                            for file_info in self.metadata)
                        if is_folder_transfer:
                            self.destination_folder = self.create_folder_structure(self.metadata)
                        else:
                            self.destination_folder = get_config()["save_to_directory"]
                        continue

                    if is_folder_transfer and self.metadata:
                        relative_file_path = file_name
                        if self.base_folder_name and relative_file_path.startswith(self.base_folder_name + '/'):
                            relative_file_path = relative_file_path[len(self.base_folder_name) + 1:]
                        full_file_path = os.path.join(self.destination_folder, relative_file_path)
                    else:
                        full_file_path = os.path.join(self.destination_folder, os.path.basename(file_name))

                    os.makedirs(os.path.dirname(full_file_path), exist_ok=True)
                    full_file_path = self._get_unique_file_name(full_file_path)
                    logger.debug(f"Saving file to: {full_file_path}")

                    with open(full_file_path, "wb") as f:
                        received_size = 0
                        remaining = file_size
                        while remaining > 0:
                            chunk_size = min(4096, remaining)
                            data = self.client_skt.recv(chunk_size)
                            if not data:
                                raise ConnectionError("Connection lost during file reception.")
                            f.write(data)
                            received_size += len(data)
                            remaining -= len(data)
                            progress = int(received_size * 100 / file_size)
                            self.progress_update.emit(progress)

                    if encrypted_transfer:
                        self.encrypted_files.append(full_file_path)

                except Exception as e:
                    logger.error(f"Error saving file {file_name}: {str(e)}")

            except Exception as e:
                logger.error("Error during file reception: %s", str(e))
                break

        self.broadcasting = True
        logger.debug("File reception completed.")

    def _receive_data(self, socket, size):
        received_data = b""
        while len(received_data) < size:
            chunk = socket.recv(size - len(received_data))
            if not chunk:
                raise ConnectionError("Connection closed before data was completely received.")
            received_data += chunk
        return received_data

    def receive_metadata(self, file_size):
        received_data = self._receive_data(self.client_skt, file_size)
        try:
            metadata_json = received_data.decode('utf-8')
            return json.loads(metadata_json)
        except UnicodeDecodeError as e:
            logger.error("Unicode decode error: %s", e)
            raise
        except json.JSONDecodeError as e:
            logger.error("JSON decode error: %s", e)
            raise

    def create_folder_structure(self, metadata):
        default_dir = get_config()["save_to_directory"]
        
        if not default_dir:
            raise ValueError("No save_to_directory configured")
        
        base_folder_name = None
        for file_info in metadata:
            path = file_info.get('path', '')
            if path.endswith('/'):
                base_folder_name = path.rstrip('/').split('/')[0]
                logger.debug("Found base folder name: %s", base_folder_name)
                break

        if not base_folder_name:
            base_folder_name = metadata[-1].get('base_folder_name', '')
            logger.debug("Base folder name from last metadata entry: %s", base_folder_name)

        if not base_folder_name:
            raise ValueError("Base folder name not found in metadata")
        
        destination_folder = os.path.join(default_dir, base_folder_name)
        destination_folder = self._get_unique_folder_name(destination_folder)
        logger.debug("Destination folder: %s", destination_folder)
        
        if not os.path.exists(destination_folder):
            os.makedirs(destination_folder)
            logger.debug("Created root folder: %s", destination_folder)
        
        self.base_folder_name = base_folder_name
        
        return destination_folder

    def _get_unique_file_name(self, file_path):
        if not os.path.exists(file_path):
            return file_path
        
        base_name, extension = os.path.splitext(file_path)
        counter = 1
        
        while os.path.exists(f"{base_name} ({counter}){extension}"):
            counter += 1
            
        return f"{base_name} ({counter}){extension}"

    def _get_unique_folder_name(self, folder_path):
        if not os.path.exists(folder_path):
            return folder_path
        
        counter = 1
        while os.path.exists(f"{folder_path} ({counter})"):
            counter += 1
            
        return f"{folder_path} ({counter})"

    def stop(self):
        self.broadcasting = False
        if hasattr(self, 'server_skt') and self.server_skt:
            try:
                self.server_skt.close()
            except:
                pass
        if hasattr(self, 'client_skt') and self.client_skt:
            try:
                self.client_skt.close()
            except:
                pass

    def close_connection(self):
        self.stop()

class ReceiveWorkerPython(BaseReceiveWorker):
    def __init__(self, client_ip):
        super().__init__(client_ip)
        self.close_connection_signal = pyqtSignal()
        self.close_connection_signal.connect(self.close_connection)

class ReceiveWorkerJava(BaseReceiveWorker):
    pass

class ReceiveWorkerSwift(BaseReceiveWorker):
    pass

class BaseReceiveApp(QWidget):
    def __init__(self, client_ip):
        super().__init__()
        self.client_ip = client_ip
        self.setFixedSize(853, 480)
        self.current_text = ""
        self.displayed_text = ""
        self.char_index = 0
        self.initUI()
        self.setup_receiver()

    def initUI(self):
        self.setWindowTitle('Receive File')
        self.setGeometry(100, 100, 853, 480)
        self.center_window()
        self.setStyleSheet("""
            QWidget {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 1,
                    stop: 0 #b0b0b0,
                    stop: 1 #505050
                );
            }
        """)

        receiving_gif_path = os.path.join(os.path.dirname(__file__), "assets", "file.gif")
        success_gif_path = os.path.join(os.path.dirname(__file__), "assets", "mark.gif")

        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)

        self.loading_label = QLabel(self)
        self.loading_label.setStyleSheet("QLabel { background-color: transparent; border: none; }")
        self.receiving_movie = QMovie(receiving_gif_path)
        self.success_movie = QMovie(success_gif_path)
        self.receiving_movie.setScaledSize(QtCore.QSize(100, 100))
        self.success_movie.setScaledSize(QtCore.QSize(100, 100))
        self.loading_label.setMovie(self.receiving_movie)
        self.receiving_movie.start()
        layout.addWidget(self.loading_label, alignment=Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter)

        self.label = QLabel("", self)
        self.label.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 28px;
                background: transparent;
                border: none;
                font-weight: bold;
            }
        """)
        layout.addWidget(self.label, alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #2f3642;
                color: white;
                border: 1px solid #4b5562;
                border-radius: 5px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
            }
        """)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.open_dir_button = self.create_styled_button('Open Receiving Directory')
        self.open_dir_button.clicked.connect(self.open_receiving_directory)
        self.open_dir_button.setVisible(False)
        layout.addWidget(self.open_dir_button)

        self.close_button = self.create_styled_button('Close')
        self.close_button.setVisible(False)
        self.close_button.clicked.connect(self.close)
        layout.addWidget(self.close_button)

        self.mainmenu_button = self.create_styled_button('Main Menu')
        self.mainmenu_button.setVisible(False)
        self.mainmenu_button.clicked.connect(self.openMainWindow)
        layout.addWidget(self.mainmenu_button)

        self.setLayout(layout)

        self.typewriter_timer = QTimer(self)
        self.typewriter_timer.timeout.connect(self.update_typewriter_effect)
        self.typewriter_timer.start(50)

    def setup_receiver(self):
        self.file_receiver.progress_update.connect(self.updateProgressBar)
        self.file_receiver.decrypt_signal.connect(self.decryptor_init)
        self.file_receiver.receiving_started.connect(self.show_progress_bar)
        self.file_receiver.transfer_finished.connect(self.onTransferFinished)
        QMetaObject.invokeMethod(self.file_receiver, "start", Qt.ConnectionType.QueuedConnection)

    def create_styled_button(self, text):
        button = QPushButton(text)
        button.setFixedHeight(25)
        button.setFont(QFont("Arial", 14))
        button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 #2f3642,
                    stop: 1 #4b5562
                );
                color: white;
                border-radius: 8px;
                border: 1px solid rgba(0, 0, 0, 0.5);
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 #3c4450,
                    stop: 1 #5a6476
                );
            }
            QPushButton:pressed {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 #232933,
                    stop: 1 #414b58
                );
            }
            QPushButton:disabled {
                background: #666;
                color: #aaa;
            }
        """)
        return button

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self.openMainWindow()

    def openMainWindow(self):
        from main import MainApp
        self.main_window = MainApp()
        self.main_window.show()
        self.close()

    def center_window(self):
        screen = QScreen.availableGeometry(QApplication.primaryScreen())
        window_width, window_height = 853, 480
        x = (screen.width() - window_width) // 2
        y = (screen.height() - window_height) // 2
        self.setGeometry(x, y, window_width, window_height)

    def show_progress_bar(self):
        self.progress_bar.setVisible(True)
        self.label.setText(self.get_progress_text())

    def update_typewriter_effect(self):
        if self.char_index < len(self.current_text):
            self.displayed_text += self.current_text[self.char_index]
            self.label.setText(self.displayed_text)
            self.char_index += 1
        else:
            self.typewriter_timer.stop()

    def updateProgressBar(self, value):
        self.progress_bar.setValue(value)

    def onTransferFinished(self):
        self.label.setText("File received successfully!")
        self.open_dir_button.setVisible(True)
        self.change_gif_to_success()
        self.close_button.setVisible(True)

    def change_gif_to_success(self):
        self.receiving_movie.stop()
        self.loading_label.setMovie(self.success_movie)
        self.success_movie.start()

    def decryptor_init(self, value):
        logger.debug("Received decrypt signal with filelist %s", value)
        if value:
            self.decryptor = Decryptor(value)
            self.decryptor.show()

    def open_receiving_directory(self):
        receiving_dir = get_config().get("save_to_directory", "")
        if receiving_dir:
            try:
                current_os = platform.system()
                if current_os == 'Windows':
                    os.startfile(receiving_dir)
                elif current_os == 'Linux':
                    subprocess.Popen(["xdg-open", receiving_dir])
                elif current_os == 'Darwin':
                    subprocess.Popen(["open", receiving_dir])
                else:
                    raise NotImplementedError(f"Unsupported OS: {current_os}")
            except Exception as e:
                logger.error("Failed to open directory: %s", str(e))
        else:
            logger.error("No receiving directory configured.")

    def closeEvent(self, event):
        try:
            if hasattr(self, 'typewriter_timer'):
                self.typewriter_timer.stop()
            if hasattr(self, 'file_receiver'):
                self.file_receiver.stop()
                if not self.file_receiver.wait(3000):
                    self.file_receiver.terminate()
                    self.file_receiver.wait()
            if hasattr(self, 'receiving_movie'):
                self.receiving_movie.stop()
            if hasattr(self, 'success_movie'):
                self.success_movie.stop()
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
        finally:
            event.accept()

class ReceiveAppP(BaseReceiveApp):
    def __init__(self, client_ip, sender_os):
        self.sender_os = sender_os
        super().__init__(client_ip)
        self.file_receiver = ReceiveWorkerPython(client_ip)
        self.current_text = self.displaytxt()

    def displaytxt(self):
        match self.sender_os:
            case 'Windows':
                return 'Waiting to receive files from a Windows device'
            case 'Linux':
                return 'Waiting to receive files from a Linux device'
            case 'Darwin':
                return 'Waiting to receive files from a macOS device'
            case _:
                return 'Waiting to receive files from Desktop app'

    def get_progress_text(self):
        match self.sender_os:
            case 'Windows':
                return 'Receiving files from a Windows device'
            case 'Linux':
                return 'Receiving files from a Linux device'
            case 'Darwin':
                return 'Receiving files from a macOS device'
            case _:
                return 'Receiving files from Desktop app'

class ReceiveAppPJava(BaseReceiveApp):
    def __init__(self, client_ip):
        super().__init__(client_ip)
        self.file_receiver = ReceiveWorkerJava(client_ip)
        self.current_text = "Waiting to receive files from an Android device"

    def get_progress_text(self):
        return "Receiving files from an Android device"

class ReceiveAppPSwift(BaseReceiveApp):
    def __init__(self, client_ip):
        super().__init__(client_ip)
        self.file_receiver = ReceiveWorkerSwift(client_ip)
        self.current_text = "Waiting to receive files from a Swift device"

    def get_progress_text(self):
        return "Receiving files from a Swift device"

class FileReceiver(QThread):
    show_receive_app_p_signal = pyqtSignal(str)
    show_receive_app_p_signal_java = pyqtSignal()
    show_receive_app_p_signal_swift = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.encrypted_files = []
        self.broadcasting = True
        self.metadata = None
        self.destination_folder = None
        self.client_ip = None
        self.server_socket = None
        self.client_socket = None
        self.receiver_worker = None

    def run(self):
        try:
            if self.server_socket:
                self.server_socket.close()
                sleep(0.5)
            if self.client_socket:
                self.client_socket.close()
                sleep(0.5)
            if self.receiver_worker:
                self.receiver_worker.terminate()
        except Exception:
            pass

        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind(('0.0.0.0', RECEIVER_JSON))
        self.server_socket.listen(5)

        while True:
            self.client_socket, addr = self.server_socket.accept()
            self.store_client_ip()
            self.handle_device_type()
            self.client_socket.close()

    def store_client_ip(self):
        self.client_ip = self.client_socket.getpeername()[0]
        logger.debug(f"Client IP address stored: {self.client_ip}")
        return self.client_ip

    def handle_device_type(self):
        device_data = {
            "device_type": "python",
            "os": platform.system()
        }
        device_data_json = json.dumps(device_data)
        self.client_socket.send(struct.pack('<Q', len(device_data_json)))
        self.client_socket.send(device_data_json.encode())

        device_json_size = struct.unpack('<Q', self.client_socket.recv(8))[0]
        device_json = self.client_socket.recv(device_json_size).decode()
        self.device_info = json.loads(device_json)
        
        match self.device_info.get("device_type", "unknown"):
            case "python":
                logger.debug("Connected to a Python device.")
                self.show_receive_app_p_signal.emit(self.device_info.get("os", "unknown"))
            case "java":
                logger.debug("Connected to a Java device.")
                self.show_receive_app_p_signal_java.emit()
            case "swift":
                logger.debug("Connected to a Swift device.")
                self.show_receive_app_p_signal_swift.emit()
            case _:
                logger.debug("Unknown device type received.")
        
        sleep(1)
        self.cleanup_sockets()

    def cleanup_sockets(self):
        if self.client_socket:
            self.client_socket.close()

class ReceiveApp(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()
        self.setFixedSize(853, 480)

    def initUI(self):
        self.setWindowTitle('Receive File')
        self.setGeometry(100, 100, 853, 480)
        self.center_window()
        self.setStyleSheet("""
            QWidget {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 1,
                    stop: 0 #b0b0b0,
                    stop: 1 #505050
                );
            }
        """)

        gif_path = os.path.join(os.path.dirname(__file__), "assets", "loading.gif")
        layout = QVBoxLayout()
        hbox = QHBoxLayout()
        
        self.loading_label = QLabel(self)
        self.loading_label.setStyleSheet("QLabel { background-color: transparent; border: none; }")
        self.movie = QMovie(gif_path)
        self.movie.setScaledSize(QtCore.QSize(40, 40))
        self.loading_label.setMovie(self.movie)
        self.movie.start()
        hbox.addWidget(self.loading_label)

        self.label = QLabel("", self)
        self.label.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 28px;
                background: transparent;
                border: none;
                font-weight: bold;
            }
        """)
        hbox.addWidget(self.label)
        hbox.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addLayout(hbox)

        self.setLayout(layout)

        self.file_receiver = FileReceiver()
        self.file_receiver.show_receive_app_p_signal.connect(self.show_receive_app_p)
        self.file_receiver.show_receive_app_p_signal_java.connect(self.show_receive_app_p_java)
        self.file_receiver.show_receive_app_p_signal_swift.connect(self.show_receive_app_p_swift)
        self.file_receiver.start()

        self.broadcast_thread = threading.Thread(target=self.listenForBroadcast, daemon=True)
        self.broadcast_thread.start()

        self.start_typewriter_effect("Waiting to connect to sender")

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self.openMainWindow()

    def openMainWindow(self):
        from main import MainApp
        self.main_app = MainApp()
        self.main_app.show()
        self.close()

    def start_typewriter_effect(self, full_text, interval=50):
        self.full_text = full_text
        self.text_index = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_text)
        self.timer.start(interval)

    def update_text(self):
        self.text_index += 1
        self.label.setText(self.full_text[:self.text_index])
        if self.text_index >= len(self.full_text):
            self.timer.stop()

    def listenForBroadcast(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(('', BROADCAST_PORT))

            while True:
                if self.file_receiver.broadcasting:
                    message, address = s.recvfrom(1024)
                    message = message.decode()
                    if message == 'DISCOVER':
                        response = f'RECEIVER:{get_config()["device_name"]}'
                        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as response_socket:
                            response_socket.sendto(response.encode(), (address[0], LISTEN_PORT))
                sleep(1)

    def connection_successful(self):
        self.movie.stop()
        self.loading_label.hide()
        self.label.setText("Connected successfully!")
        self.label.setStyleSheet("color: #00FF00;")

    def show_receive_app_p(self, sender_os):
        client_ip = self.file_receiver.client_ip
        self.hide()
        self.receive_app_p = ReceiveAppP(client_ip, sender_os)
        self.receive_app_p.show()

    def show_receive_app_p_java(self):
        client_ip = self.file_receiver.client_ip
        self.hide()
        self.receive_app_p_java = ReceiveAppPJava(client_ip)
        self.receive_app_p_java.show()

    def show_receive_app_p_swift(self):
        client_ip = self.file_receiver.client_ip
        self.hide()
        self.receive_app_p_swift = ReceiveAppPSwift(client_ip)
        self.receive_app_p_swift.show()

    def center_window(self):
        screen = QScreen.availableGeometry(QApplication.primaryScreen())
        window_width, window_height = 853, 480
        x = (screen.width() - window_width) // 2
        y = (screen.height() - window_height) // 2
        self.setGeometry(x, y, window_width, window_height)

    def closeEvent(self, event):
        try:
            if self.file_receiver:
                self.file_receiver.terminate()
                self.stop()
        except AttributeError:
            pass
        self.file_receiver.broadcasting = False
        event.accept()

    def stop(self):
        self.file_receiver.broadcasting = False
        self.file_receiver.server_socket.close()
        self.file_receiver.client_socket.close()
        self.file_receiver.receiver_worker.terminate()

class BaseReceiveApp(QWidget):
    def __init__(self, client_ip):
        super().__init__()
        self.client_ip = client_ip
        self.setFixedSize(853, 480)
        self.initUI()

    def initUI(self):
        self.setWindowTitle('Receive File')
        self.setGeometry(100, 100, 853, 480)
        self.center_window()
        self.setStyleSheet("""
            QWidget {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 1,
                    stop: 0 #b0b0b0,
                    stop: 1 #505050
                );
            }
        """)

        layout = QVBoxLayout()

        # Loading GIF setup
        gif_path = os.path.join(os.path.dirname(__file__), "assets", "loading.gif")
        success_gif_path = os.path.join(os.path.dirname(__file__), "assets", "success.gif")

        hbox = QHBoxLayout()
        
        self.loading_label = QLabel(self)
        self.loading_label.setStyleSheet("QLabel { background-color: transparent; border: none; }")
        
        self.receiving_movie = QMovie(gif_path)
        self.success_movie = QMovie(success_gif_path)
        
        for movie in [self.receiving_movie, self.success_movie]:
            movie.setScaledSize(QtCore.QSize(40, 40))
        
        self.loading_label.setMovie(self.receiving_movie)
        self.receiving_movie.start()
        
        hbox.addWidget(self.loading_label)

        self.label = QLabel(self.current_text, self)
        self.label.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 28px;
                background: transparent;
                border: none;
                font-weight: bold;
            }
        """)
        hbox.addWidget(self.label)
        hbox.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addLayout(hbox)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #2f3642;
                color: white;
                border: 1px solid #4b5562;
                border-radius: 5px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
            }
        """)
        layout.addWidget(self.progress_bar)

        # Buttons
        self.open_dir_button = self.create_styled_button('Open Receiving Directory')
        self.open_dir_button.clicked.connect(self.open_receiving_directory)
        self.open_dir_button.setVisible(False)
        layout.addWidget(self.open_dir_button)

        self.close_button = self.create_styled_button('Close')
        self.close_button.setVisible(False)
        self.close_button.clicked.connect(self.close)
        layout.addWidget(self.close_button)

        self.mainmenu_button = self.create_styled_button('Main Menu')
        self.mainmenu_button.setVisible(False)
        self.mainmenu_button.clicked.connect(self.openMainWindow)
        layout.addWidget(self.mainmenu_button)

        self.setLayout(layout)

        # Connect signals
        if hasattr(self, 'file_receiver'):
            self.file_receiver.progress_update.connect(self.updateProgressBar)
            self.file_receiver.receiving_started.connect(self.show_progress_bar)
            self.file_receiver.decrypt_signal.connect(self.decryptor_init)
            self.file_receiver.transfer_finished.connect(self.onTransferFinished)
            self.file_receiver.start()

    def create_styled_button(self, text):
        button = QPushButton(text)
        button.setFixedHeight(25)
        button.setFont(QFont("Arial", 14))
        button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 #2f3642,
                    stop: 1 #4b5562
                );
                color: white;
                border-radius: 8px;
                border: 1px solid rgba(0, 0, 0, 0.5);
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 #3c4450,
                    stop: 1 #5a6476
                );
            }
            QPushButton:pressed {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 #232933,
                    stop: 1 #414b58
                );
            }
            QPushButton:disabled {
                background: #666;
                color: #aaa;
            }
        """)
        return button

    def center_window(self):
        screen = QScreen.availableGeometry(QApplication.primaryScreen())
        window_width, window_height = 853, 480
        x = (screen.width() - window_width) // 2
        y = (screen.height() - window_height) // 2
        self.setGeometry(x, y, window_width, window_height)

    def show_progress_bar(self):
        self.progress_bar.setVisible(True)
        self.label.setText(self.get_progress_text())

    def updateProgressBar(self, value):
        self.progress_bar.setValue(value)
        if value >= 100:
            self.onTransferFinished()

    def onTransferFinished(self):
        self.label.setText("File received successfully!")
        self.open_dir_button.setVisible(True)
        self.change_gif_to_success()
        self.close_button.setVisible(True)
        self.mainmenu_button.setVisible(True)

    def change_gif_to_success(self):
        self.receiving_movie.stop()
        self.loading_label.setMovie(self.success_movie)
        self.success_movie.start()

    def decryptor_init(self, value):
        logger.debug("Received decrypt signal with filelist %s", value)
        if value:
            self.decryptor = Decryptor(value)
            self.decryptor.show()

    def open_receiving_directory(self):
        receiving_dir = get_config().get("save_to_directory", "")
        if receiving_dir:
            try:
                match platform.system():
                    case 'Windows':
                        os.startfile(receiving_dir)
                    case 'Linux':
                        subprocess.Popen(["xdg-open", receiving_dir])
                    case 'Darwin':
                        subprocess.Popen(["open", receiving_dir])
                    case _:
                        raise NotImplementedError(f"Unsupported OS: {platform.system()}")
            except Exception as e:
                logger.error(f"Failed to open directory: {str(e)}")
        else:
            logger.error("No receiving directory configured.")

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self.openMainWindow()

    def openMainWindow(self):
        from main import MainApp
        self.main_window = MainApp()
        self.main_window.show()
        self.close()

    def closeEvent(self, event):
        try:
            if hasattr(self, 'typewriter_timer'):
                self.typewriter_timer.stop()
            if hasattr(self, 'file_receiver'):
                self.file_receiver.stop()
                if not self.file_receiver.wait(3000):
                    self.file_receiver.terminate()
                    self.file_receiver.wait()
            if hasattr(self, 'receiving_movie'):
                self.receiving_movie.stop()
            if hasattr(self, 'success_movie'):
                self.success_movie.stop()
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
        finally:
            event.accept()

if __name__ == '__main__':
    import sys
    app = QApplication(sys.argv)
    receive_app = ReceiveApp()
    receive_app.show()
    sys.exit(app.exec())