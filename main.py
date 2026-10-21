import sys

import capture

capture.set_dpi_aware()

from PySide6.QtWidgets import QApplication  # noqa: E402

from ui import MainWindow  # noqa: E402

if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
