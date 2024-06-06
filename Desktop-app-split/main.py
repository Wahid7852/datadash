import sys
from PyQt6.QtWidgets import QApplication
from main_app import MainApp

if __name__ == '__main__':
    app = QApplication(sys.argv)
    main_app = MainApp()
    main_app.show()
    sys.exit(app.exec())
