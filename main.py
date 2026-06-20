import sys
from PyQt6.QtWidgets import QApplication
from utils.logger import setup_logger
from ui.main_window import MainWindow


def main() -> None:
    setup_logger(".")
    app = QApplication(sys.argv)
    win = MainWindow(output_dir=".")
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
