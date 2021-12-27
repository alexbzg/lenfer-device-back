from machine import Pin, Onewire, UART
import ubinascii
import logging

LOG = logging.getLogger("Sensors")

class SensorDevice:
    "generic sensor handler"

    def __init__(self, conf, controller):
        self.sensor_type = conf['type']
        self._controller = controller
        self._sensors_ids = conf['sensors_ids']
        if controller:
            for sensor_id in self._sensors_ids:
                if not sensor_id in controller.data:
                    controller.data[sensor_id] = None

class SensorDevicePZEM004T(SensorDevice):
    "PZEM-004T sensor handler"

    def __init__(self, conf, controller):
        SensorDevice.__init__(self, conf, controller)
        self._uart = UART(conf['uart']['id'], tx=conf['uart']['tx'], rx=conf['uart']['rx'], baudrate=9600, timeout=3)
        self._uart.init()

    def read(self):
        "reads sensors data and stores in into controller data field"
        self._uart.write(b"\xf8\x04\x00\x00\x00\x0a\x64\x64")   
        msg_raw = self._uart.read(25)
        if msg_raw:
            try:
                msg = ubinascii.hexlify(msg_raw).decode()
                self._controller.data[self._sensors_ids[0]] = int(msg[6:10], 16) / 10 #volatge
                self._controller.data[self._sensors_ids[1]] = int(msg[10:14], 16) / 1000 #current
            except Exception as exc:
                LOG.exc(exc, 'PZEM UART reading error')

class SensorDeviceBME280(SensorDevice):
    "BME280 sensor handler"

    def __init__(self, conf, controller, i2c_list):
        SensorDevice.__init__(self, conf, controller)
        self._i2c = i2c_list[conf['i2c']]

    def read(self):
        "reads sensors data and stores in into controller data field"
        humid, temp = None, None
        try:
            import BME280
            bme = BME280.BME280(i2c=self._i2c)
            temp = round((bme.read_temperature() / 100), 1)
            humid = int(bme.read_humidity() // 1024)
        except Exception as exc:
            pass
            #LOG.exc(exc, 'BME280 error')
        finally:
            self._controller.data[self._sensors_ids[0]] = temp
            self._controller.data[self._sensors_ids[1]] = humid

class SensorDeviceAHT20(SensorDevice):
    "AHT20 sensor handler"

    def __init__(self, conf, controller, i2c_list):
        SensorDevice.__init__(self, conf, controller)
        try:
            import ahtx0
            self._ahtx0 = ahtx0.AHT20(i2c_list[conf['i2c']])
        except Exception as exc:
            LOG.exc(exc, 'AHTX0 initialization error')

    def read(self):
        "reads sensors data and stores in into controller data field"
        humid, temp = None, None
        try:
            temp = self._ahtx0.temperature
            humid = self._ahtx0.relative_humidity
        except Exception as exc:
            pass
            #LOG.exc(exc, 'BME280 error')
        finally:
            self._controller.data[self._sensors_ids[0]] = temp
            self._controller.data[self._sensors_ids[1]] = humid

class SensorDeviceCCS811(SensorDevice):
    "CCS811 sensor handler"

    def __init__(self, conf, controller, i2c_list):
        SensorDevice.__init__(self, conf, controller)
        self._ccs811 = None
        try:
            from CCS811 import CCS811
            self._ccs811 = CCS811(i2c_list[conf['i2c']])
        except Exception as exc:
            LOG.exc(exc, 'CCS811 initialization error')

    def read(self):
        "reads sensors data and stores in into controller data field"
        if self._ccs811:
            co2 = None
            try:
                if self._ccs811.data_ready():
                    co2 = self._ccs811.eCO2
                    temp = self._controller.data[self._controller.sensors_roles['temperature'][0]]
                    humid = self._controller.data[self._controller.sensors_roles['humidity'][0]]
                    if temp != None and humid != None:
                        self._ccs811.put_envdata(humid, temp)
            except Exception as exc:
                pass
                #LOG.exc(exc, 'BME280 error')
            finally:
                if co2:
                    self._controller.data[self._sensors_ids[0]] = co2

class SensorDeviceDS18x20(SensorDevice):
    "ds18x20 sensor handler"

    def __init__(self, conf, controller, ow_list):
        SensorDevice.__init__(self, conf, controller)
        print('ds18x20 init')
        self.rom = None
        self._ow = None
        self._ds = None
        _ow = ow_list[conf['ow']]
        if _ow:
            self._ow = Onewire(Pin(ow_list[conf['ow']]))
            ow_roms = self._ow.scan()
            if ow_roms:
                self.rom = ow_roms[0]
                print('ds18x20 rom found ' + str(self.rom))
                self._ds = Onewire.ds18x20(self._ow, 0)
            else:
                print('no ds18x20 rom found')
        else:
            print('invalid onewire settings')
        self._convert = False

    def convert(self):
        "requests sensor readings"
        if self.rom:
            try:
                self._ds.convert(False)
                self._convert = True
            except Exception as exc:
                LOG.exc(exc, 'onewire error')

    def read(self):
        "reads sensors data and stores in into controller data field"
        if self._convert:
            try:
                self._controller.data[self._sensors_ids[0]] =\
                    round(self._ds.read_temp(), 1)
            except Exception as exc:
                LOG.exc(exc, 'onewire error')
                self._controller.data[self._sensors_ids[0]] = None
            finally:
                self._convert = False

