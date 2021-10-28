"""MicroPython library for the INA219 sensor.

This library supports the INA219 sensor from Texas Instruments with
MicroPython using the I2C bus.
"""
import utime
from math import trunc
from micropython import const


class INA219:
    """Provides all the functionality to interact with the INA219 sensor."""

    RANGE_16V = const(0)  # Range 0-16 volts
    RANGE_32V = const(1)  # Range 0-32 volts

    GAIN_1_40MV = const(0)  # Maximum shunt voltage 40mV
    GAIN_2_80MV = const(1)  # Maximum shunt voltage 80mV
    GAIN_4_160MV = const(2)  # Maximum shunt voltage 160mV
    GAIN_8_320MV = const(3)  # Maximum shunt voltage 320mV
    GAIN_AUTO = const(-1)  # Determine gain automatically

    ADC_9BIT = const(0)  # 9-bit conversion time  84us.
    ADC_10BIT = const(1)  # 10-bit conversion time 148us.
    ADC_11BIT = const(2)  # 11-bit conversion time 2766us.
    ADC_12BIT = const(3)  # 12-bit conversion time 532us.
    ADC_2SAMP = const(9)  # 2 samples at 12-bit, conversion time 1.06ms.
    ADC_4SAMP = const(10)  # 4 samples at 12-bit, conversion time 2.13ms.
    ADC_8SAMP = const(11)  # 8 samples at 12-bit, conversion time 4.26ms.
    ADC_16SAMP = const(12)  # 16 samples at 12-bit,conversion time 8.51ms
    ADC_32SAMP = const(13)  # 32 samples at 12-bit, conversion time 17.02ms.
    ADC_64SAMP = const(14)  # 64 samples at 12-bit, conversion time 34.05ms.
    ADC_128SAMP = const(15)  # 128 samples at 12-bit, conversion time 68.10ms.

    __ADDRESS = 0x40

    __REG_CONFIG = 0x00
    __REG_SHUNTVOLTAGE = 0x01
    __REG_BUSVOLTAGE = 0x02
    __REG_POWER = 0x03
    __REG_CURRENT = 0x04
    __REG_CALIBRATION = 0x05

    __RST = 15
    __BRNG = 13
    __PG0 = 11
    __BADC1 = 7
    __SADC1 = 3

    __OVF = 1

    __BUS_RANGE = [16, 32]
    __GAIN_VOLTS = [0.04, 0.08, 0.16, 0.32]

    __CONT_SH_BUS = 7

    __AMP_ERR_MSG = ('Expected current %.3fA is greater '
                     'than max possible current %.3fA')
    __RNG_ERR_MSG = ('Expected amps %.2fA, out of range, use a lower '
                     'value shunt resistor')
    __VOLT_ERR_MSG = ('Invalid voltage range, must be one of: '
                      'RANGE_16V, RANGE_32V')

    __SHUNT_MILLIVOLTS_LSB = 0.01  # 10uV
    __BUS_MILLIVOLTS_LSB = 4  # 4mV
    __CALIBRATION_FACTOR = 0.04096
    __MAX_CALIBRATION_VALUE = 0xFFFE
    __CURRENT_LSB_FACTOR = 32800

    def __init__(self, shunt_ohms, i2c, max_expected_amps=None,
                 address=__ADDRESS):
        self._i2c = i2c
        self._address = address
        self._shunt_ohms = shunt_ohms
        self._max_expected_amps = max_expected_amps
        self._min_device_current_lsb = self._calculate_min_current_lsb()
        self._gain = None
        self._auto_gain_enabled = False

    def configure(self, voltage_range=RANGE_32V, gain=GAIN_AUTO,
                  bus_adc=ADC_12BIT, shunt_adc=ADC_12BIT):
        self.__validate_voltage_range(voltage_range)
        self._voltage_range = voltage_range

        if self._max_expected_amps is not None:
            if gain == self.GAIN_AUTO:
                self._auto_gain_enabled = True
                self._gain = self._determine_gain(self._max_expected_amps)
            else:
                self._gain = gain
        else:
            if gain != self.GAIN_AUTO:
                self._gain = gain
            else:
                self._auto_gain_enabled = True
                self._gain = self.GAIN_1_40MV

        self._calibrate(
            self.__BUS_RANGE[voltage_range], self.__GAIN_VOLTS[self._gain],
            self._max_expected_amps)
        self._configure(voltage_range, self._gain, bus_adc, shunt_adc)

    def voltage(self):
        value = self._voltage_register()
        return float(value) * self.__BUS_MILLIVOLTS_LSB / 1000

    def supply_voltage(self):
        return self.voltage() + (float(self.shunt_voltage()) / 1000)

    def current(self):
        self._handle_current_overflow()
        return self._current_register() * self._current_lsb * 1000

    def power(self):
        self._handle_current_overflow()
        return self._power_register() * self._power_lsb * 1000

    def shunt_voltage(self):
        self._handle_current_overflow()
        return self._shunt_voltage_register() * self.__SHUNT_MILLIVOLTS_LSB

    def sleep(self):
        configuration = self._read_configuration()
        self._configuration_register(configuration & 0xFFF8)

    def wake(self):
        configuration = self._read_configuration()
        self._configuration_register(configuration | 0x0007)
        utime.sleep_us(40)

    def current_overflow(self):
        return self._has_current_overflow()

    def reset(self):
        self._configuration_register(1 << self.__RST)

    def _handle_current_overflow(self):
        if self._auto_gain_enabled:
            while self._has_current_overflow():
                self._increase_gain()
        else:
            if self._has_current_overflow():
                raise DeviceRangeError(self.__GAIN_VOLTS[self._gain])

    def _determine_gain(self, max_expected_amps):
        shunt_v = max_expected_amps * self._shunt_ohms
        if shunt_v > self.__GAIN_VOLTS[3]:
            raise ValueError(self.__RNG_ERR_MSG % max_expected_amps)
        gain = min(v for v in self.__GAIN_VOLTS if v > shunt_v)
        return self.__GAIN_VOLTS.index(gain)

    def _increase_gain(self):
        self._log.info(self.__LOG_MSG_3)
        gain = self._read_gain()
        if gain < len(self.__GAIN_VOLTS) - 1:
            gain = gain + 1
            self._calibrate(self.__BUS_RANGE[self._voltage_range],
                            self.__GAIN_VOLTS[gain])
            self._configure_gain(gain)
            utime.sleep_ms(1)
        else:
            raise DeviceRangeError(self.__GAIN_VOLTS[gain], True)

    def _configure(self, voltage_range, gain, bus_adc, shunt_adc):
        configuration = (
            voltage_range << self.__BRNG | gain << self.__PG0 |
            bus_adc << self.__BADC1 | shunt_adc << self.__SADC1 |
            self.__CONT_SH_BUS)
        self._configuration_register(configuration)

    def _calibrate(self, bus_volts_max, shunt_volts_max,
                   max_expected_amps=None):
        max_possible_amps = shunt_volts_max / self._shunt_ohms

        self._current_lsb = \
            self._determine_current_lsb(max_expected_amps, max_possible_amps)

        self._power_lsb = self._current_lsb * 20

        calibration = trunc(self.__CALIBRATION_FACTOR /
                            (self._current_lsb * self._shunt_ohms))
        self._calibration_register(calibration)

    def _determine_current_lsb(self, max_expected_amps, max_possible_amps):
        if max_expected_amps is not None:
            if max_expected_amps > round(max_possible_amps, 3):
                raise ValueError(self.__AMP_ERR_MSG %
                                 (max_expected_amps, max_possible_amps))
            self._log.info("max expected current: %.3fA", max_expected_amps)
            if max_expected_amps < max_possible_amps:
                current_lsb = max_expected_amps / self.__CURRENT_LSB_FACTOR
            else:
                current_lsb = max_possible_amps / self.__CURRENT_LSB_FACTOR
        else:
            current_lsb = max_possible_amps / self.__CURRENT_LSB_FACTOR

        if current_lsb < self._min_device_current_lsb:
            current_lsb = self._min_device_current_lsb
        return current_lsb

    def _configuration_register(self, register_value):
        self.__write_register(self.__REG_CONFIG, register_value)

    def _read_configuration(self):
        return self.__read_register(self.__REG_CONFIG)

    def _calculate_min_current_lsb(self):
        return self.__CALIBRATION_FACTOR / \
            (self._shunt_ohms * self.__MAX_CALIBRATION_VALUE)

    def _read_gain(self):
        configuration = self._read_configuration()
        gain = (configuration & 0x1800) >> self.__PG0
        return gain

    def _configure_gain(self, gain):
        configuration = self._read_configuration()
        configuration = configuration & 0xE7FF
        self._configuration_register(configuration | (gain << self.__PG0))
        self._gain = gain

    def _calibration_register(self, register_value):
        self.__write_register(self.__REG_CALIBRATION, register_value)

    def _has_current_overflow(self):
        ovf = self._read_voltage_register() & self.__OVF
        return (ovf == 1)

    def _voltage_register(self):
        register_value = self._read_voltage_register()
        return register_value >> 3

    def _read_voltage_register(self):
        return self.__read_register(self.__REG_BUSVOLTAGE)

    def _current_register(self):
        return self.__read_register(self.__REG_CURRENT, True)

    def _shunt_voltage_register(self):
        return self.__read_register(self.__REG_SHUNTVOLTAGE, True)

    def _power_register(self):
        return self.__read_register(self.__REG_POWER)

    def __validate_voltage_range(self, voltage_range):
        if voltage_range > len(self.__BUS_RANGE) - 1:
            raise ValueError(self.__VOLT_ERR_MSG)

    def __write_register(self, register, register_value):
        register_bytes = self.__to_bytes(register_value)
        self._i2c.writeto_mem(self._address, register, register_bytes)

    def __to_bytes(self, register_value):
        return bytearray([(register_value >> 8) & 0xFF, register_value & 0xFF])

    def __read_register(self, register, negative_value_supported=False):
        register_bytes = self._i2c.readfrom_mem(self._address, register, 2)
        register_value = int.from_bytes(register_bytes, 'big')
        if negative_value_supported:
            if register_value > 32767:
                register_value -= 65536

        return register_value

class DeviceRangeError(Exception):

    __DEV_RNG_ERR = ('Current out of range (overflow), '
                     'for gain %.2fV')

    def __init__(self, gain_volts, device_max=False):
        msg = self.__DEV_RNG_ERR % gain_volts
        if device_max:
            msg = msg + ', device limit reached'
        super(DeviceRangeError, self).__init__(msg)
        self.gain_volts = gain_volts
        self.device_limit_reached = device_max
