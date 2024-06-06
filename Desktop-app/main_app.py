from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton
from file_receiver import ReceiveApp
from file_sender import SendApp

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