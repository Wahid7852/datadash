import json
import platform
import tempfile
from pathlib import Path
from PyQt6.QtWidgets import (
    QMessageBox, QWidget, QVBoxLayout, QPushButton, QListWidget, 
    QProgressBar, QLabel, QFileDialog, QApplication, QListWidgetItem, QTextEdit, QLineEdit, QHBoxLayout, QFrame
)
from PyQt6.QtGui import QScreen, QFont, QKeyEvent, QKeySequence
import os
import socket
import struct
from PyQt6.QtCore import QThread, pyqtSignal, Qt
from constant import ConfigManager
from loges import logger
from crypt_handler import encrypt_file
from time import sleep, time
from portsss import RECEIVER_DATA_SWIFT

CHUNK_SIZE_DESKTOP = 4096

class FileSenderSwift(QThread):
    progress_update = pyqtSignal(int)
    file_send_completed = pyqtSignal(str)
    telemetry_update = pyqtSignal(float, float, float)  # Add telemetry signal
    file_count_update = pyqtSignal(int, int, int)  # total_files, files_sent, files_pending
    password = None

    def __init__(self, ip_address, file_paths, password=None, receiver_data=None):
        super().__init__()
        self.config_manager = ConfigManager()
        self.config_manager.start()
        self.ip_address = ip_address
        self.file_paths = file_paths
        self.password = password
        self.receiver_data = receiver_data
        self.total_files = self.count_total_files()
        self.files_sent = 0
        #com.an.Datadash

    def count_total_files(self):
        total = 0
        for path in self.file_paths:
            if os.path.isdir(path):
                for _, _, files in os.walk(path):
                    total += len(files)
            else:
                total += 1
        return total

    def initialize_connection(self):
        try:
            if hasattr(self, 'client_skt'):
                self.client_skt.close()
                logger.debug("Socket closed successfully before rebinding.")
            sleep(1)  # Wait for socket cleanup
            
            self.client_skt = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client_skt.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.client_skt.settimeout(30)  # 30 second timeout
            
            self.client_skt.connect((self.ip_address, RECEIVER_DATA_SWIFT))
            logger.debug(f"Successfully connected to {self.ip_address} on port 57341")
            return True
            
        except (ConnectionRefusedError, OSError) as e:
            logger.error(f"Connection failed: {e}")
            self.show_message_box("Connection Error", f"Failed to connect: {e}")
            return False

    def run(self):
        metadata_file_path = None
        self.metadata_created = False
        metadata_file_path = None
        if not self.initialize_connection():
            return
        
        # Reload config on each file transfer session
        self.config = self.config_manager.get_config()

        self.encryption_flag = self.config_manager.get_config()["swift_encryption"]
        # logger.debug("Encryption flag: %s", self.encryption_flag)

        self.file_count_update.emit(self.total_files, self.files_sent, self.total_files - self.files_sent)
        for file_path in self.file_paths:
            if os.path.isdir(file_path):
                self.send_folder(file_path)
            else:
                if not self.metadata_created:
                    metadata_file_path = self.create_metadata(file_paths=self.file_paths)
                    self.send_file(metadata_file_path)
                self.send_file(file_path, encrypted_transfer=self.encryption_flag)
                self.files_sent += 1
                self.file_count_update.emit(self.total_files, self.files_sent, self.total_files - self.files_sent)
        
        # Delete metadata file
        if self.metadata_created and metadata_file_path:
            os.remove(metadata_file_path)
            
        logger.debug("Sent halt signal")
        self.client_skt.send('encyp: h'.encode())
        self.client_skt.close()

    def get_temp_dir(self):
        system = platform.system()
        if system == "Windows":
            temp_dir = Path(os.getenv('LOCALAPPDATA')) / 'Temp' / 'DataDash'
        elif system == "Darwin":  # macOS
            temp_dir = Path.home() / 'Library' / 'Caches' / 'DataDash'
        elif system == "Linux":  # Linux and others
            temp_dir = Path.home() / '.cache' / 'DataDash'
        else:
            logger.error(f"Unsupported platform: {system}")
        
        try:
            os.makedirs(str(temp_dir), exist_ok=True)
            logger.debug(f"Created/verified temp directory: {temp_dir}")
        except Exception as e:
            logger.error(f"Failed to create temp directory: {e}")
            # Fallback to system temp directory
            temp_dir = Path(tempfile.gettempdir()) / 'DataDash'
            os.makedirs(str(temp_dir), exist_ok=True)
            logger.debug(f"Using fallback temp directory: {temp_dir}")
        
        return temp_dir

    def create_metadata(self, folder_path=None,file_paths=None):
        temp_dir = self.get_temp_dir()
        if folder_path:
            metadata = []
            for root, dirs, files in os.walk(folder_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    relative_path = os.path.relpath(file_path, folder_path)
                    file_size = os.path.getsize(file_path)
                    metadata.append({
                        'path': relative_path,
                        'size': file_size
                    })
                for dir in dirs:
                    dir_path = os.path.join(root, dir)
                    relative_path = os.path.relpath(dir_path, folder_path)
                    metadata.append({
                        'path': relative_path + '/',
                        'size': 0  # Size is 0 for directories
                    })
            metadata.append({'base_folder_name': os.path.basename(folder_path), 'path': '.delete', 'size': 0})
            metadata_json = json.dumps(metadata)
            metadata_file_path = os.path.join(temp_dir, 'metadata.json')
            with open(metadata_file_path, 'w') as f:
                f.write(metadata_json)
            self.metadata_created = True
            return metadata_file_path
        elif file_paths:
            metadata = []
            for file_path in file_paths:
                file_size = os.path.getsize(file_path)
                metadata.append({
                    'path': os.path.basename(file_path),
                    'size': file_size
                })
            metadata_json = json.dumps(metadata)
            metadata_file_path = os.path.join(temp_dir, 'metadata.json')
            with open(metadata_file_path, 'w') as f:
                f.write(metadata_json)
            self.metadata_created = True
            return metadata_file_path
            
    def send_folder(self, folder_path):
        print("Sending folder")
        
        if not self.metadata_created:
            metadata_file_path = self.create_metadata(folder_path=folder_path)
            metadata = json.loads(open(metadata_file_path).read())
            # Send metadata file
            self.send_file(metadata_file_path)
            #com.an.Datadash

        # Send all files
        for file_info in metadata:
            relative_file_path = file_info['path']
            file_path = os.path.join(folder_path, relative_file_path)
            if not relative_file_path.endswith('.delete'):
                if file_info['size'] > 0:
                    if self.encryption_flag:
                        relative_file_path += ".crypt"
                    self.send_file(file_path, relative_file_path=relative_file_path, encrypted_transfer=self.encryption_flag)
                    self.files_sent += 1
                    self.file_count_update.emit(self.total_files, self.files_sent, self.total_files - self.files_sent)
                else:
                    # Handle directory creation (if needed, in receiver)
                    pass

        # Clean up metadata file
        os.remove(metadata_file_path)

    def send_file(self, file_path, relative_file_path=None, encrypted_transfer=False):
        logger.debug("Sending file: %s", file_path)

        if encrypted_transfer:
            logger.debug("Encrypted transfer with password: %s", self.password)
            file_path = encrypt_file(file_path, self.password)

        sent_size = 0
        file_size = os.path.getsize(file_path)
        if relative_file_path is None:
            relative_file_path = os.path.basename(file_path)
        file_name_size = len(relative_file_path.encode())
        logger.debug("Sending %s, %s", relative_file_path, file_size)

        encryption_flag = 'encyp: t' if encrypted_transfer else 'encyp: f'

        self.client_skt.send(encryption_flag.encode())
        logger.debug("Sent encryption flag: %s", encryption_flag)

        self.client_skt.send(struct.pack('<Q', file_name_size))
        self.client_skt.send(relative_file_path.encode('utf-8'))
        self.client_skt.send(struct.pack('<Q', file_size))

        start_time = time()  # Start time for telemetry
        last_update_time = time()  # Track the last update time
        with open(file_path, 'rb') as f:
            while sent_size < file_size:
                data = f.read(CHUNK_SIZE_DESKTOP)
                self.client_skt.sendall(data)
                sent_size += len(data)
                self.progress_update.emit(sent_size * 100 // file_size)

                # Calculate telemetry
                elapsed_time = time() - start_time
                speed = (sent_size / elapsed_time) / (1024 * 1024) if elapsed_time > 0 else 0  # Convert to MBps
                time_remaining = (file_size - sent_size) / (speed * 1024 * 1024) if speed > 0 else 0
                total_time = elapsed_time + time_remaining

                # Update telemetry every second
                if time() - last_update_time >= 1:
                    self.telemetry_update.emit(speed, time_remaining, total_time)
                    last_update_time = time()

        self.files_sent += 1
        self.file_count_update.emit(self.total_files, self.files_sent, self.total_files - self.files_sent)

        if encrypted_transfer:
            os.remove(file_path)

        return True

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

class SendAppSwift(QWidget):
    def __init__(self,ip_address,device_name,receiver_data):
        super().__init__()
        self.config_manager = ConfigManager()
        self.config_manager.config_updated.connect(self.on_config_updated)
        self.config_manager.log_message.connect(logger.info)
        self.config_manager.start()
        self.ip_address = ip_address
        self.device_name = device_name
        self.receiver_data = receiver_data
        self.initUI()
        self.progress_bar.setVisible(False)
        self.setFixedSize(853, 480) 

    def on_config_updated(self, config):
        self.current_config = config

    def initUI(self):
        logger.debug("Encryption : %s", self.config_manager.get_config()["swift_encryption"])
        self.setWindowTitle('Send File')
        self.setGeometry(100, 100, 400, 300)
        self.center_window()
        self.set_background()

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Header
        header = QFrame()
        header.setFixedHeight(70)
        header.setStyleSheet("background-color: #333; padding: 0px;")
        header_layout = QHBoxLayout(header)

        title_label = QLabel("DataDash: Send File")
        title_label.setFont(QFont("Arial", 20, QFont.Weight.Bold))
        title_label.setStyleSheet("color: white;")
        header_layout.addWidget(title_label, alignment=Qt.AlignmentFlag.AlignCenter)

        main_layout.addWidget(header)

        # Content area
        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(30, 30, 30, 30)
        content_layout.setSpacing(20)
        #com.an.Datadash

        # File selection buttons
        button_layout = QHBoxLayout()
        self.file_button = self.create_styled_button('Select Files')
        self.file_button.clicked.connect(self.selectFile)
        button_layout.addWidget(self.file_button)

        self.folder_button = self.create_styled_button('Select Folder')
        self.folder_button.clicked.connect(self.selectFolder)
        button_layout.addWidget(self.folder_button)

        content_layout.addLayout(button_layout)

        # File path display
        self.file_path_display = QTextEdit()
        self.file_path_display.setReadOnly(True)
        self.file_path_display.setStyleSheet("""
            QTextEdit {
                background-color: #2f3642;
                color: white;
                border: 1px solid #4b5562;
                border-radius: 5px;
                padding: 5px;
            }
        """)
        content_layout.addWidget(self.file_path_display)

        # Password input (if encryption is enabled)
        if self.config_manager.get_config()['swift_encryption']:
            password_layout = QHBoxLayout()
            self.password_label = QLabel('Encryption Password:')
            self.password_label.setStyleSheet("color: white; font-size: 14px;")
            password_layout.addWidget(self.password_label)

            self.password_input = QLineEdit()
            self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.password_input.setStyleSheet("""
                QLineEdit {
                    background-color: #2f3642;
                    color: white;
                    border: 1px solid #4b5562;
                    border-radius: 5px;
                    padding: 5px;
                }
            """)
            password_layout.addWidget(self.password_input)
            content_layout.addLayout(password_layout)

        # Send button
        self.send_button = self.create_styled_button('Send Files')
        self.send_button.setVisible(False)
        self.send_button.clicked.connect(self.sendSelectedFiles)
        content_layout.addWidget(self.send_button, alignment=Qt.AlignmentFlag.AlignCenter)

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
        content_layout.addWidget(self.progress_bar)

        # Status label
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: white; font-size: 14px;")
        self.style_label(self.status_label)
        content_layout.addWidget(self.status_label, alignment=Qt.AlignmentFlag.AlignCenter)

        # Telemetry label
        self.telemetry_label = QLabel("")
        self.telemetry_label.setStyleSheet("color: white; font-size: 14px;")
        self.style_label(self.telemetry_label)
        content_layout.addWidget(self.telemetry_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self.total_files_label = QLabel("Total files: 0")
        self.total_files_label.setStyleSheet("color: white; font-size: 14px;")
        self.style_label(self.total_files_label)
        content_layout.addWidget(self.total_files_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self.completed_files_label = QLabel("Completed files: 0")
        self.completed_files_label.setStyleSheet("color: white; font-size: 14px;")
        self.style_label(self.completed_files_label)
        content_layout.addWidget(self.completed_files_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self.pending_files_label = QLabel("Pending files: 0")
        self.pending_files_label.setStyleSheet("color: white; font-size: 14px;")
        self.style_label(self.pending_files_label)
        content_layout.addWidget(self.pending_files_label, alignment=Qt.AlignmentFlag.AlignCenter)

         # Create 2 buttons for close and Transfer More Files
        # Keep them disabled until the file transfer is completed
        self.close_button = QPushButton('Close', self)
        self.close_button.setEnabled(False)
        self.close_button.setVisible(False)
        self.close_button.clicked.connect(self.close)
        content_layout.addWidget(self.close_button)

        self.mainmenu_button = self.create_styled_button('Main Menu')
        self.mainmenu_button.setVisible(False)
        self.mainmenu_button.clicked.connect(self.openMainWindow)
        content_layout.addWidget(self.mainmenu_button)

        main_layout.addLayout(content_layout)
        self.setLayout(main_layout)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self.openMainWindow()

    def openMainWindow(self):
        from main import MainApp
        self.main_window = MainApp()
        self.main_window.show()
        self.close()

    def create_styled_button(self, text):
        button = QPushButton(text)
        button.setFixedSize(150, 50)
        button.setFont(QFont("Arial", 14))
        button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 #2f3642,
                    stop: 1 #4b5562
                );
                color: white;
                border-radius: 25px;
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

    def set_background(self):
        self.setStyleSheet("""
            QWidget {
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 1,
                    stop: 0 #b0b0b0,
                    stop: 1 #505050
                );
            }
        """)

    def style_label(self, label):
        label.setStyleSheet("""
            color: #FFFFFF;
            background-color: transparent;  /* Set the background to transparent */
        """)

    def center_window(self):
        screen = QScreen.availableGeometry(QApplication.primaryScreen())
        window_width, window_height = 853, 480
        x = (screen.width() - window_width) // 2
        y = (screen.height() - window_height) // 2
        self.setGeometry(x, y, window_width, window_height)
        #com.an.Datadash

    def selectFile(self):
        documents= self.get_default_path()
        file_paths, _ = QFileDialog.getOpenFileNames(self, 'Open Files', documents)
        if file_paths:
            self.file_path_display.clear()
            for file_path in file_paths:
                self.file_path_display.append(file_path)
            self.file_paths = file_paths
            self.checkReadyToSend()

    def selectFolder(self):
        documents= self.get_default_path()
        folder_path = QFileDialog.getExistingDirectory(self, 'Select Folder', documents)
        if folder_path:
            self.file_path_display.clear()
            self.file_path_display.append(folder_path)
            self.file_paths = [folder_path]
            print(self.file_paths)
            self.checkReadyToSend()

    def get_default_path(self):
        if platform.system() == 'Windows':
            return os.path.expanduser('~\\Documents')
        elif platform.system() == 'Linux':
            return os.path.expanduser('~/Documents')
        elif platform.system() == 'Darwin':  # macOS
            return os.path.expanduser('~/Documents')
        else:
            logger.error("Unsupported OS!")
            return os.path.expanduser('~')  # Fallback to home directory

    def checkReadyToSend(self):
        if self.file_paths:
            self.send_button.setVisible(True)

    def sendSelectedFiles(self):
        selected_item = self.device_name
        password = None

        if not selected_item:
            QMessageBox.critical(None, "Selection Error", "Please select a device to send the file.")
            return
        ip_address = self.ip_address
        print(self.file_paths)

        if self.config_manager.get_config()['swift_encryption']:
            password = self.password_input.text()
            if not self.password_input.text():
                QMessageBox.critical(None, "Password Error", "Please enter a password.")
                return

        self.send_button.setVisible(False)
        self.file_sender_swift = FileSenderSwift(ip_address, self.file_paths, password, self.receiver_data)
        self.progress_bar.setVisible(True)
        self.file_sender_swift.progress_update.connect(self.updateProgressBar)
        self.file_sender_swift.file_send_completed.connect(self.fileSent)
        self.file_sender_swift.telemetry_update.connect(self.updateTelemetry)  # Connect telemetry signal
        self.file_sender_swift.file_count_update.connect(self.updateFileCounts)
        self.file_sender_swift.start()
        #com.an.Datadash

    def updateProgressBar(self, value):
        self.progress_bar.setValue(value)
        if value >= 100:
            self.status_label.setText("File transfer completed!")
            self.status_label.setStyleSheet("color: white; font-size: 14px; background-color: transparent;")

            
            # Enable the close and Transfer More Files buttons
            self.close_button.setEnabled(True)
            self.close_button.setVisible(True)
            # self.mainmenu_button.setVisible(True)

    def updateTelemetry(self, speed, time_remaining, total_time):
        self.telemetry_label.setText(f"Speed: {speed:.2f} MBps | Time remaining: {time_remaining:.2f} s | Total time: {total_time:.2f} s")

    def updateFileCounts(self, total_files, files_sent, files_pending):
        self.total_files_label.setText(f"Total files: {total_files}")
        self.completed_files_label.setText(f"Completed files: {files_sent}")
        self.pending_files_label.setText(f"Pending files: {files_pending}")

    def fileSent(self, file_path):
        self.status_label.setText(f"File sent: {file_path}")

    def closeEvent(self, event):
        try:
            """Override the close event to ensure everything is stopped properly."""
            if self.file_sender and self.file_sender.isRunning():
                self.file_sender.stop()  # Signal the sender to stop
                self.file_sender.wait()  # Wait until the thread fully stops
        except Exception as e:
            pass
        finally:
            event.accept()

    def stop(self):
        """Sets the stop signal to True and closes the socket if it's open."""
        self.stop_signal = True
        if self.client_skt:
            try:
                self.client_skt.close()
            except Exception as e:
                logger.error(f"Error while closing socket: {e}")

if __name__ == '__main__':
    import sys
    app = QApplication(sys.argv)
    send_app = SendAppSwift()
    send_app.show()
    sys.exit(app.exec())
    #com.an.Datadash
