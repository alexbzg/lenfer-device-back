from machine import UART

class UARTconsole():

    def __init__(self, tx=27, rx=26):
        self._uart = UART(1, 9600, tx=tx, rx=rx)
        self._uart.init(baudrate=9600, tx=tx, rx=rx)

    def read(self):
        while self._uart.any():
            print(self._uart.read(self._uart.any()))

    def write(self, str):
        self._uart.write("{}\r\n".format(str))
        self.read()
        self.read()