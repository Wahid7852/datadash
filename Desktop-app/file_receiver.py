import os
import platform
import socket
import struct
import threading
from PyQt6.QtCore import QThread, pyqtSignal, QTimer, Qt
from PyQt6 import QtCore
from PyQt6.QtWidgets import (
    QMessageBox, QWidget, QVBoxLayout, QLabel, QProgressBar, QApplication, QHBoxLayout
)
from PyQt6.QtGui import QScreen, QMovie, QKeySequence, QKeyEvent
from constant import ConfigManager
from portsss import BROADCAST_PORT, LISTEN_PORT, RECEIVER_JSON
from loges import logger
from time import sleep, time
import json
from file_receiver_python import ReceiveAppP
from file_receiver_android import ReceiveAppPJava
from file_receiver_swift import ReceiveAppPSwift


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
        self.config_manager = ConfigManager()
        self.config_manager.start()

    def run(self):
        logger.info("Starting FileReceiver thread")
        try:
            if self.server_socket:
                logger.debug("Closing existing server socket")
                self.server_socket.close()
                sleep(0.5)
            if self.client_socket:
                logger.debug("Closing existing client socket")
                self.client_socket.close()
                sleep(0.5)
            if self.receiver_worker:
                logger.debug("Terminating existing receiver worker")
                self.receiver_worker.terminate()
        except Exception as e:
            logger.error(f"Error cleaning up existing connections: {str(e)}")

        logger.info("Initializing new server socket")
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.server_socket.bind(('0.0.0.0', RECEIVER_JSON))
            logger.info(f"Server bound to port {RECEIVER_JSON}")
            self.server_socket.listen(5)
            logger.info("Server listening for connections")

            while True:
                logger.debug("Waiting for incoming connection")
                self.client_socket, addr = self.server_socket.accept()
                logger.info(f"New connection accepted from {addr}")
                self.store_client_ip()
                self.handle_device_type()
                self.client_socket.close()

        except Exception as e:
            logger.error(f"Critical error in server operation: {str(e)}")

    def store_client_ip(self):
        self.client_ip = self.client_socket.getpeername()[0]
        logger.debug(f"Client IP address stored: {self.client_ip}")
        return self.client_ip

    def handle_device_type(self):
        logger.info("Handling device type negotiation")
        try:
            device_data = {
                "device_type": "python",
                "os": platform.system()
            }
            device_data_json = json.dumps(device_data)
            logger.debug(f"Sending device data: {device_data}")
            
            self.client_socket.send(struct.pack('<Q', len(device_data_json)))
            self.client_socket.send(device_data_json.encode())
            logger.debug(f"Device data sent to {self.client_socket.getpeername()}")

            logger.debug("Waiting for sender device information")
            device_json_size = struct.unpack('<Q', self.client_socket.recv(8))[0]
            device_json = self.client_socket.recv(device_json_size).decode()
            self.device_info = json.loads(device_json)
            
            sender_device_type = self.device_info.get("device_type", "unknown")
            sender_os = self.device_info.get("os", "unknown")
            logger.info(f"Connected to device type: {sender_device_type}, OS: {sender_os}")

            if sender_device_type == "python":
                logger.info("Initializing Python device connection")
                self.show_receive_app_p_signal.emit(sender_os)
            elif sender_device_type == "java":
                logger.info("Initializing Java device connection")
                self.show_receive_app_p_signal_java.emit()
            elif sender_device_type == "swift":
                logger.info("Initializing Swift device connection")
                self.show_receive_app_p_signal_swift.emit()
            else:
                logger.warning(f"Unknown device type received: {sender_device_type}")
            
            sleep(1)
            self.cleanup_sockets()

        except Exception as e:
            logger.error(f"Error in device type handling: {str(e)}")
    
    def cleanup_sockets(self):
        if self.client_socket:
            self.client_socket.close()


class ReceiveWorkerPython(QThread):
    # ...existing code...

    def receive_files(self):
        self.broadcasting = False  # Stop broadcasting
        logger.debug("File reception started.")

        while True:
            try:
                # Receive and decode encryption flag
                encryption_flag = self.client_skt.recv(8).decode()
                logger.debug("Received encryption flag: %s", encryption_flag)

                if not encryption_flag:
                    logger.debug("Dropped redundant data: %s", encryption_flag)
                    break
                # ...existing code...

                if encryption_flag[-1] == 't':
                    encrypted_transfer = True
                elif encryption_flag[-1] == 'h':
                    # Halting signal, break transfer and decrypt files
                    if self.encrypted_files:
                        self.decrypt_signal.emit(self.encrypted_files)
                    self.encrypted_files = []
                    logger.debug("Received halt signal. Stopping file reception.")
                    self.transfer_finished.emit()
                    break
                else:
                    encrypted_transfer = False

                # Receive file name size
                file_name_size_data = self.client_skt.recv(8)
                file_name_size = struct.unpack('<Q', file_name_size_data)[0]
                logger.debug("File name size received: %d", file_name_size)

                if file_name_size == 0:
                    logger.debug("End of transfer signal received.")
                    break  # End of transfer signal

                # Receive file name and normalize the path
                file_name = self._receive_data(self.client_skt, file_name_size).decode()

                # Convert Windows-style backslashes to Unix-style forward slashes
                file_name = file_name.replace('\\', '/')
                logger.debug("Normalized file name: %s", file_name)

                # Receive file size
                file_size_data = self.client_skt.recv(8)
                file_size = struct.unpack('<Q', file_size_data)[0]
                logger.debug("Receiving file %s, size: %d bytes", file_name, file_size)

                start_time = time()  # Start time for telemetry
                received_size = 0
                last_update_time = time()  # Track the last update time

                # Check if it's metadata
                if file_name == 'metadata.json':
                    logger.debug("Receiving metadata file.")
                    self.metadata = self.receive_metadata(file_size)
                    self.total_files = len(self.metadata)  # Include the last entry (base folder info)
                    self.file_count_update.emit(self.total_files, self.files_received, self.total_files - self.files_received)
                    # ...existing code...
                else:
                    # ...existing code...

                    # Receive file data in chunks
                    with open(file_path, "wb") as f:
                        while received_size < file_size:
                            chunk_size = min(CHUNK_SIZE_DESKTOP, file_size - received_size)
                            data = self._receive_data(self.client_skt, chunk_size)
                            if not data:
                                logger.error("Failed to receive data. Connection may have been closed.")
                                break
                            f.write(data)
                            received_size += len(data)
                            logger.debug("Received %d/%d bytes for file %s", received_size, file_size, file_name)
                            self.progress_update.emit(received_size * 100 // file_size)

                            # Calculate telemetry
                            elapsed_time = time() - start_time
                            speed = (received_size / elapsed_time) / (1024 * 1024) if elapsed_time > 0 else 0  # Convert to Mbps
                            time_remaining = (file_size - received_size) / (speed * 1024 * 1024) if speed > 0 else 0
                            total_time = elapsed_time + time_remaining

                            # Update telemetry every second
                            if time() - last_update_time >= 1:
                                self.telemetry_update.emit(speed, time_remaining, total_time)
                                last_update_time = time()

                            logger.info(f"Speed: {speed:.2f} Mbps | Time remaining: {time_remaining:.2f} s | Total time: {total_time:.2f} s")

                    self.files_received += 1
                    pending_files = max(self.total_files - self.files_received, 0)  # Ensure pending files do not go below 0
                    self.file_count_update.emit(self.total_files, self.files_received, pending_files)

            except Exception as e:
                logger.error("Error during file reception: %s", str(e))
                break

        logger.debug("File reception completed.")

    # ...existing code...


class ReceiveApp(QWidget):
    def __init__(self):
        super().__init__()
        logger.info("Initializing ReceiveApp")
        self.config_manager = ConfigManager()
        self.config_manager.config_updated.connect(self.on_config_updated)
        self.config_manager.log_message.connect(logger.info)
        self.config_manager.start()
        self.initUI()
        self.setFixedSize(853, 480)
        #com.an.Datadash

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
        self.movie = QMovie(gif_path)  # Use the relative path to load the GIF
        self.movie.setScaledSize(QtCore.QSize(40, 40)) 
        self.loading_label.setMovie(self.movie)
        self.movie.start()
        hbox.addWidget(self.loading_label)

        # Label with typewriter effect
        self.label = QLabel("", self)  # Empty string initially
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


        #layout = QVBoxLayout()

        # self.label = QLabel("Waiting for Connection...", self)
        # layout.addWidget(self.label)

        self.setLayout(layout)

        self.file_receiver = FileReceiver()
        self.file_receiver.show_receive_app_p_signal.connect(self.show_receive_app_p)
        self.file_receiver.show_receive_app_p_signal_java.connect(self.show_receive_app_p_java)
        self.file_receiver.show_receive_app_p_signal_swift.connect(self.show_receive_app_p_swift)
        self.file_receiver.start()
        #com.an.Datadash

        self.broadcast_thread = threading.Thread(target=self.listenForBroadcast, daemon=True)
        self.broadcast_thread.start()
# Call the method to start typewriter effect
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
        """Starts the typewriter effect to show text character by character."""
        self.full_text = full_text
        self.text_index = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_text)
        self.timer.start(interval)

    def update_text(self):
        """Updates the label with one more character."""
        self.text_index += 1
        self.label.setText(self.full_text[:self.text_index])
        if self.text_index >= len(self.full_text):
            self.timer.stop()
            #com.an.Datadash

    def listenForBroadcast(self):
        logger.info("Starting broadcast listener")
        search_socket = None
        reply_socket = None
        try:
            # Socket for searching broadcasts
            search_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            search_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            search_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            search_socket.bind(('0.0.0.0', BROADCAST_PORT))  # Listen on port 49185
            logger.info(f"Searching for broadcasts on port {BROADCAST_PORT}")

            while True:
                if self.file_receiver.broadcasting:
                    try:
                        message, address = search_socket.recvfrom(1024)
                        message = message.decode()
                        logger.debug(f"Received broadcast message: {message} from {address}")
                        
                        if message == 'DISCOVER':
                            device_name = self.config_manager.get_config()["device_name"]
                            response = f'RECEIVER:{device_name}'
                            logger.info(f"Sending response as {device_name} to {address[0]}")
                            
                            # Create new socket for sending response
                            reply_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                            reply_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                            reply_socket.sendto(response.encode(), (address[0], LISTEN_PORT))  # Send to port 49186
                            reply_socket.close()
                            logger.debug(f"Response sent to {address[0]}:{LISTEN_PORT}")
                    except Exception as e:
                        logger.error(f"Error handling broadcast message: {str(e)}")
                    sleep(1)

        except Exception as e:
            logger.error(f"Critical error in broadcast listener: {str(e)}")
        finally:
            if search_socket:
                search_socket.close()

    def connection_successful(self):
        self.movie.stop()
        self.loading_label.hide()
        self.label.setText("Connected successfully!")
        self.label.setStyleSheet("color: #00FF00;")  # Green color for success
        #com.an.Datadash


    def show_receive_app_p(self, sender_os):
        client_ip = self.file_receiver.client_ip
        """Slot to show the ReceiveAppP window on the main thread."""
        self.hide()
        self.receive_app_p = ReceiveAppP(client_ip, sender_os)
        self.receive_app_p.show()

    def show_receive_app_p_java(self):
        client_ip = self.file_receiver.client_ip
        """Slot to show the ReceiveAppP window on the main thread."""
        self.hide()
        self.receive_app_p_java = ReceiveAppPJava(client_ip)
        self.receive_app_p_java.show()

    def show_receive_app_p_swift(self):
        client_ip = self.file_receiver.client_ip
        """Slot to show the ReceiveAppP window on the main thread."""
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
        logger.info("Shutting down ReceiveApp")
        try:
            """Override the close event to ensure everything is stopped properly."""
            if self.file_receiver:
                logger.debug("Terminating file receiver")
                self.file_receiver.terminate()
                self.stop()
        except AttributeError as e:
            logger.error(f"Error during shutdown: {str(e)}")
        
        logger.debug("Stopping broadcast thread")
        self.file_receiver.broadcasting = False
        logger.info("ReceiveApp shutdown complete")
        event.accept()

    def stop(self):
        self.file_receiver.broadcasting = False
        self.file_receiver.server_socket.close()
        self.file_receiver.client_socket.close()
        self.file_receiver.receiver_worker.terminate()

    def on_config_updated(self, config):
        """Handle configuration updates."""
        logger.debug(f"Receiver config updated: {config}")
        # Update any UI elements or settings based on the new config if needed
        pass

    def updateTelemetry(self, speed, time_remaining, total_time):
        self.telemetry_label.setText(f"Speed: {speed:.2f} Mbps | Time remaining: {time_remaining:.2f} s | Total time: {total_time:.2f} s")

if __name__ == '__main__':
    import sys
    app = QApplication([])
    receive_app = ReceiveApp()
    receive_app.show()
    app.exec()
    #com.an.Datadash