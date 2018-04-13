"""
Defunct <defunct<at>defunct.io> - NOP Developments LLC. 2016

MIT License

Copyright (c) <2016> <NOP Developments LLC>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt

class BinjaButtonHolderWidget(QtWidgets.QDockWidget):
    """Binja Button Holder Widget:
        A dockable toolbar widget that can hold text buttons, image buttons, and combo boxes
    """
    def __init__(self, *__args):
        super(BinjaButtonHolderWidget, self).__init__(*__args)
        self._app = QtWidgets.QApplication.instance()
        self._main_window = [x for x in self._app.allWidgets() if x.__class__ is QtWidgets.QMainWindow][0]
        self._tool_menu = [x for x in self._main_window.menuWidget().children() if x.__class__ is QtWidgets.QMenu and x.title() == u'&Tools'][0]
        self._main_window.addDockWidget(Qt.TopDockWidgetArea, self)
        self._toolbar = QtWidgets.QToolBar()
        self.setWidget(self._toolbar)
        self.hide()

    def add_widget(self, widj):
        self._toolbar.addWidget(widj)

    def addToolMenuAction(self, name, function):
        """ Adds an item to the tool menu (at the top of the window) without registering a plugin command """
        self._tool_menu.addAction(name, function)

    def clear_all_widgets(self):
        self._toolbar.clear()

    def toggle(self):
        """ Toggles visibility (obviously) """
        if self.isVisible():
            self.hide()
        else:
            self.show()

    @property
    def app(self):
        return self._app

    @property
    def main_window(self):
        return self._main_window
