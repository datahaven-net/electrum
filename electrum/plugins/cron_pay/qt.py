#!/usr/bin/env python
#
# Electrum - Lightweight Bitcoin Client
# Copyright (C) 2015 Thomas Voegtlin
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
# BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
# ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import os
import json
import stat

from datetime import datetime

from enum import IntEnum

from PyQt5.QtGui import QStandardItemModel, QStandardItem
from PyQt5.QtCore import Qt, QItemSelectionModel
from PyQt5.QtWidgets import QPushButton, QVBoxLayout, QLabel, QGridLayout, QLineEdit

from electrum.gui.qt.util import Buttons, CloseButton, OkButton, HelpLabel, WindowModalDialog, MyTreeView, read_QIcon

from electrum.crypto import sha256

from electrum.plugin import BasePlugin, hook
from electrum.i18n import _

from electrum.util import user_dir, bh2u
from electrum.util import PR_TYPE_ONCHAIN, PR_TYPE_LN


def read_schedule_file():
    schedule_path = os.path.join(user_dir(), 'schedule')
    if not os.path.exists(schedule_path):
        return {}    
    try:
        with open(schedule_path, "r", encoding='utf-8') as f:
            data = f.read()
        result = json.loads(data)
    except:
        return {}
    if not type(result) is dict:
        return {}
    return result


def write_schedule_file(schedule_dict):
    schedule_path = os.path.join(user_dir(), 'schedule')
    s = json.dumps(schedule_dict, indent=4, sort_keys=True)
    try:
        with open(schedule_path, "w", encoding='utf-8') as f:
            f.write(s)
        os.chmod(schedule_path, stat.S_IREAD | stat.S_IWRITE)
    except FileNotFoundError:
        if os.path.exists(schedule_path):
            raise


ROLE_REQUEST_TYPE = Qt.UserRole
ROLE_REQUEST_ID = Qt.UserRole + 1


class CronPaymentsList(MyTreeView):

    class Columns(IntEnum):
        ADDRESS = 0
        AMOUNT = 1
        DESCRIPTION = 2
        LAST_TIME = 3
        NEXT_TIME = 4

    headers = {
        Columns.ADDRESS: _('Address'),
        Columns.AMOUNT: _('Amount'),
        Columns.DESCRIPTION: _('Description'),
        Columns.LAST_TIME: _('Last payment'),
        Columns.NEXT_TIME: _('Next payment'),
    }
    filter_columns = [Columns.LAST_TIME, Columns.NEXT_TIME, Columns.AMOUNT]

    def __init__(self, parent):
        super().__init__(parent, lambda: None,
                         stretch_column=self.Columns.DESCRIPTION,
                         editable_columns=[])
        self.setMinimumSize(900, 200)
        self.setSortingEnabled(True)
        self.setModel(QStandardItemModel(self))
        self.update()

    def update(self):
        current_schedule = read_schedule_file()
        _list = current_schedule.get('items', [])
        self.model().clear()
        self.update_headers(self.__class__.headers)
        for idx, cron_item in enumerate(_list):
            item = cron_item['invoice']
            schedule = cron_item['schedule']
            invoice_type = item['type']
            if invoice_type == PR_TYPE_LN:
                key = item['rhash']
                icon_name = 'lightning.png'
            elif invoice_type == PR_TYPE_ONCHAIN:
                key = bh2u(sha256(repr(item))[0:16])
                icon_name = 'bitcoin.png'
                if item.get('bip70'):
                    icon_name = 'seal.png'
            else:
                raise Exception('Unsupported type')
            address_str = item['outputs'][0][1]
            message = item['message']
            amount = item['amount']
            amount_str = self.parent.format_amount(amount, whitespaces=True)
            last_str = ''
            next_str = ''
            try:
                from croniter import croniter
                cron = '{minute} {hour} {day} {month} {week}'.format(**schedule)
                item = croniter(cron, datetime.now())
                next_str = item.get_next(datetime).isoformat()
            except:
                pass
            labels = [address_str, amount_str, message, last_str, next_str, ]
            items = [QStandardItem(e) for e in labels]
            self.set_editability(items)
            items[self.Columns.ADDRESS].setIcon(read_QIcon(icon_name))
            items[self.Columns.ADDRESS].setData(key, role=ROLE_REQUEST_ID)
            items[self.Columns.ADDRESS].setData(invoice_type, role=ROLE_REQUEST_TYPE)
            self.model().insertRow(idx, items)
        self.selectionModel().select(self.model().index(0,0), QItemSelectionModel.SelectCurrent)
        self.filter()


class CronPaymentsDialog(WindowModalDialog):

    def __init__(self, parent, title=None):
        WindowModalDialog.__init__(self, parent, title=title)
        vbox = QVBoxLayout(self)
        cron_list = CronPaymentsList(parent)
        vbox.addWidget(cron_list)
        vbox.addStretch()
        vbox.addLayout(Buttons(QPushButton('Edit'), QPushButton('Delete'), ))
        vbox.addStretch()
        vbox.addLayout(Buttons(CloseButton(self), ))


class ScheduleDialog(WindowModalDialog):

    def __init__(self, main_win, outputs):
        WindowModalDialog.__init__(self, main_win, title=_("New scheduled payment"),)
        vbox = QVBoxLayout(self)
        self.setMinimumSize(400, 150)
        minute_label = HelpLabel(_('minute:'), _('''
Defines a specific minute for an hour.
Allowed characters:
"*" any value
"," value list separator
"-" range of values
"/" step values
0-59 allowed values
'''))
        hour_label = HelpLabel(_('hour:'), _('''
Defines a specific hour during the day.
Allowed characters:
"*" any value
"," value list separator
"-" range of values
"/" step values
0-23 allowed values
'''))
        day_label = HelpLabel(_('day of month:'), _('''
Defines the day number for the month.
Allowed characters:
"*" any value
"," value list separator
"-" range of values
"/" step values
0-31 allowed values
'''))
        month_label = HelpLabel(_('month:'), _('''
Defines a month during the year.
Allowed characters:
"*" any value
"," value list separator
"-" range of values
"/" step values
1-12 allowed values
'''))
        week_label = HelpLabel(_('day of week:'), _('''
Specifies the day of the week.
Allowed characters:
"*" any value
"," value list separator
"-" range of values
"/" step values
0-6 allowed values
'''))
        self.minute_edit = QLineEdit('*')
        self.minute_edit.setFixedWidth(30)
        self.minute_edit.textChanged.connect(self.update_schedule_details)
        self.hour_edit = QLineEdit('*')
        self.hour_edit.setFixedWidth(30)
        self.hour_edit.textChanged.connect(self.update_schedule_details)
        self.day_edit = QLineEdit('*')
        self.day_edit.setFixedWidth(30)
        self.day_edit.textChanged.connect(self.update_schedule_details)
        self.month_edit = QLineEdit('*')
        self.month_edit.setFixedWidth(30)
        self.month_edit.textChanged.connect(self.update_schedule_details)
        self.week_edit = QLineEdit('*')
        self.week_edit.setFixedWidth(30)
        self.week_edit.textChanged.connect(self.update_schedule_details)
        grid = QGridLayout()
        grid.addWidget(minute_label, 0, 0, alignment=Qt.AlignCenter)
        grid.addWidget(hour_label, 0, 1, alignment=Qt.AlignCenter)
        grid.addWidget(day_label, 0, 2, alignment=Qt.AlignCenter)
        grid.addWidget(month_label, 0, 3, alignment=Qt.AlignCenter)
        grid.addWidget(week_label, 0, 4, alignment=Qt.AlignCenter)
        grid.addWidget(self.minute_edit, 1, 0, alignment=Qt.AlignCenter)
        grid.addWidget(self.hour_edit, 1, 1, alignment=Qt.AlignCenter)
        grid.addWidget(self.day_edit, 1, 2, alignment=Qt.AlignCenter)
        grid.addWidget(self.month_edit, 1, 3, alignment=Qt.AlignCenter)
        grid.addWidget(self.week_edit, 1, 4, alignment=Qt.AlignCenter)
        every_day = QPushButton('every day')
        every_day.clicked.connect(lambda: self.set_as_text('0 0 * * *'))
        every_week = QPushButton('every week')
        every_week.clicked.connect(lambda: self.set_as_text('0 0 * * 0'))
        every_month = QPushButton('every month')
        every_month.clicked.connect(lambda: self.set_as_text('0 0 1 * *'))
        every_year = QPushButton('every year')
        every_year.clicked.connect(lambda: self.set_as_text('0 0 1 1 *'))
        self.schedule_details = QLabel('')
        vbox.addLayout(grid)
        vbox.addLayout(Buttons(every_day, every_week, every_month, every_year))
        vbox.addWidget(self.schedule_details)
        vbox.addStretch()
        vbox.addLayout(Buttons(CloseButton(self), OkButton(self)))
        self.update_schedule_details()

    def set_as_text(self, value):
        items = value.split(' ')
        self.minute_edit.setText(items[0])
        self.minute_edit.repaint()
        self.hour_edit.setText(items[1])
        self.hour_edit.repaint()
        self.day_edit.setText(items[2])
        self.day_edit.repaint()
        self.month_edit.setText(items[3])
        self.month_edit.repaint()
        self.week_edit.setText(items[4])
        self.week_edit.repaint()
        self.update_schedule_details()

    def update_schedule_details(self):
        try:
            from croniter import croniter
            item = croniter(self.as_text(), datetime.now())
            t = item.get_next(datetime)
        except:
            self.schedule_details.setText('')
            return
        self.schedule_details.setText('new payment expected on:\n%s' % t.strftime("%A, %d %B %Y at %I:%M%p"))

    def as_text(self):
        return '%s %s %s %s %s' % (
            self.minute_edit.text(),
            self.hour_edit.text(),
            self.day_edit.text(),
            self.month_edit.text(),
            self.week_edit.text(),
        )

    def as_dict(self):
        return {
            'minute': self.minute_edit.text(),
            'hour': self.hour_edit.text(),
            'day': self.day_edit.text(),
            'month': self.month_edit.text(),
            'week': self.week_edit.text(),
        }


class ScheduleButton(QPushButton):

    def __init__(self, main_window):
        QPushButton.__init__(self, _("Schedule"))
        self.clicked.connect(lambda: self._on_clicked(main_window))

    def _on_clicked(self, main_win):
        outputs = main_win.read_outputs()
        if main_win.check_send_tab_outputs_and_show_errors(outputs):
            return
        d = ScheduleDialog(main_win, outputs)
        d.show()
        if not d.exec_():
            return
        invoice = main_win.read_invoice()
        if not invoice:
            return
        current_schedule = read_schedule_file()
        if 'items' not in current_schedule:
            current_schedule['items'] = []

        current_schedule['items'].append({
            'invoice': invoice,
            'schedule': d.as_dict(),
        })
        write_schedule_file(current_schedule)
        main_win.do_clear()
        main_win.show_message(_('New automatic payment scheduled successfully'))


class Plugin(BasePlugin):

    def fullname(self):
        return 'Cron Payments'

    def description(self):
        return _("Automated scheduled BitCoin payments")

    def is_available(self):
        return True

    def __init__(self, parent, config, name):
        BasePlugin.__init__(self, parent, config, name)
        self.start_scheduler()

    def on_cron_payments_menu_clicked(self, window, tools_menu):
        d = CronPaymentsDialog(window, _("Scheduled payments"))
        d.show()

    @hook
    def init_menubar_tools(self, main_window, tools_menu):
        tools_menu.addSeparator()
        tools_menu.addAction(_("&Scheduled payments"), lambda: self.on_cron_payments_menu_clicked(main_window, tools_menu))
        buttons = main_window.send_grid.itemAtPosition(6, 1)
        schedule_button = ScheduleButton(main_window)
        buttons.addWidget(schedule_button)

    def execute_payment(self):
        # TODO: to be continue
        pass

    def start_scheduler(self):
        # TODO: to be continue
        pass
