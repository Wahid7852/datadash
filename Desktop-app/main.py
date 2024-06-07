from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QApplication
from PyQt6.QtGui import QScreen
from file_receiver import ReceiveApp
from file_sender import SendApp
import sys

class MainApp(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()

    def initUI(self):
        self.setWindowTitle('Media Sharing App')
        self.setGeometry(100, 100, 300, 200)
        self.center_window()

        layout = QVBoxLayout()

        self.send_button = QPushButton('Send File', self)
        self.send_button.clicked.connect(self.sendFile)
        layout.addWidget(self.send_button)

        self.receive_button = QPushButton('Receive File', self)
        self.receive_button.clicked.connect(self.receiveFile)
        layout.addWidget(self.receive_button)

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

    def sendFile(self):
        self.hide()
        self.send_app = SendApp()
        self.send_app.show()

    def receiveFile(self):
        self.hide()
        self.receive_app = ReceiveApp()
        self.receive_app.show()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    main = MainApp()
    main.show()
    sys.exit(app.exec())