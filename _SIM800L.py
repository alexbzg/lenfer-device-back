
import re
import utime as time
import ujson as json

# Setup logging.
try:
    import logging
    logger = logging.getLogger(__name__)
except:
    try:
        import logger
    except:
        class Logger(object):
            level = 'DEBUG'
            @classmethod
            def debug(cls, text):
                if cls.level == 'DEBUG': print('DEBUG:', text)
            @classmethod
            def info(cls, text):
                print('INFO:', text)
            @classmethod
            def warning(cls, text):
                print('WARN:', text)
        logger = Logger()


class GenericATError(Exception):
    pass

class ReadTimeoutException(Exception):
    pass

class Response(object):

    def __init__(self, status_code, content):
        self.status_code = int(status_code)
        self.content     = content


class Modem(object):

    def __init__(self, uart=None, MODEM_PWKEY_PIN=4, MODEM_RST_PIN=5, MODEM_POWER_ON_PIN=23, MODEM_TX_PIN=26, MODEM_RX_PIN=27):

        # Pins
        self.MODEM_PWKEY_PIN    = MODEM_PWKEY_PIN
        self.MODEM_RST_PIN      = MODEM_RST_PIN
        self.MODEM_POWER_ON_PIN = MODEM_POWER_ON_PIN
        self.MODEM_TX_PIN       = MODEM_TX_PIN
        self.MODEM_RX_PIN       = MODEM_RX_PIN

        # Uart
        self.uart = uart

        self.initialized = False
        self.modem_info = None


    #----------------------
    #  Modem initializer
    #----------------------

    def initialize(self):

        logger.debug('Initializing modem...')

        if not self.uart:
            from machine import UART, Pin

            # Pin initialization
            MODEM_PWKEY_PIN_OBJ = Pin(self.MODEM_PWKEY_PIN, Pin.OUT) if self.MODEM_PWKEY_PIN else None
            MODEM_RST_PIN_OBJ = Pin(self.MODEM_RST_PIN, Pin.OUT) if self.MODEM_RST_PIN else None
            MODEM_POWER_ON_PIN_OBJ = Pin(self.MODEM_POWER_ON_PIN, Pin.OUT) if self.MODEM_POWER_ON_PIN else None
            #MODEM_TX_PIN_OBJ = Pin(self.MODEM_TX_PIN, Pin.OUT) # Not needed as we use MODEM_TX_PIN
            #MODEM_RX_PIN_OBJ = Pin(self.MODEM_RX_PIN, Pin.IN)  # Not needed as we use MODEM_RX_PIN

            # Status setup
            if MODEM_PWKEY_PIN_OBJ:
                MODEM_PWKEY_PIN_OBJ.value(0)
            if MODEM_RST_PIN_OBJ:
                MODEM_RST_PIN_OBJ.value(1)
            if MODEM_POWER_ON_PIN_OBJ:
                MODEM_POWER_ON_PIN_OBJ.value(1)

            # Setup UART
            self.uart = UART(1, 9600, timeout=1000, rx=self.MODEM_TX_PIN, tx=self.MODEM_RX_PIN)

        # Test AT commands
        retries = 0
        while True:
            try:
                self.modem_info = self.execute_at_command('modeminfo')
            except:
                retries+=1
                if retries < 3:
                    logger.debug('Error in getting modem info, retrying.. (#{})'.format(retries))
                    time.sleep(3)
                else:
                    raise
            else:
                break

        logger.debug('Ok, modem "{}" is ready and accepting commands'.format(self.modem_info))

        # Set initialized flag and support vars
        self.initialized = True
        
        # Check if SSL is supported
        self.ssl_available = self.execute_at_command('checkssl') == '+CIPSSL: (0-1)'


    #----------------------
    # Execute AT commands
    #----------------------
    def execute_at_command(self, command, data=None, clean_output=True, buf_size=None, yield_buf=False, binary_output=False):
        # Commands dictionary. Not the best approach ever, but works nicely.
        commands = {
                    'modeminfo':  {'string':'ATI', 'timeout':3, 'end': 'OK'},
                    'fwrevision': {'string':'AT+CGMR', 'timeout':3, 'end': 'OK'},
                    'battery':    {'string':'AT+CBC', 'timeout':3, 'end': 'OK'},
                    'scan':       {'string':'AT+COPS=?', 'timeout':60, 'end': 'OK'},
                    'network':    {'string':'AT+COPS?', 'timeout':3, 'end': 'OK'},
                    'signal':     {'string':'AT+CSQ', 'timeout':3, 'end': 'OK'},
                    'checkreg':   {'string':'AT+CREG?', 'timeout':3, 'end': None},
                    'setapn':     {'string':'AT+SAPBR=3,1,"APN","{}"'.format(data), 'timeout':3, 'end': 'OK'},
                    'setuser':    {'string':'AT+SAPBR=3,1,"USER","{}"'.format(data), 'timeout':3, 'end': 'OK'},
                    'setpwd':     {'string':'AT+SAPBR=3,1,"PWD","{}"'.format(data), 'timeout':3, 'end': 'OK'},
                    'initgprs':   {'string':'AT+SAPBR=3,1,"Contype","GPRS"', 'timeout':3, 'end': 'OK'}, # Appeared on hologram net here or below
                    'opengprs':   {'string':'AT+SAPBR=1,1', 'timeout':3, 'end': 'OK'},
                    'getbear':    {'string':'AT+SAPBR=2,1', 'timeout':5, 'end': 'OK'},
                    'inithttp':   {'string':'AT+HTTPINIT', 'timeout':3, 'end': 'OK'},
                    'sethttp':    {'string':'AT+HTTPPARA="CID",1', 'timeout':3, 'end': 'OK'},
                    'checkssl':   {'string':'AT+CIPSSL=?', 'timeout': 3, 'end': 'OK'},
                    'enablessl':  {'string':'AT+HTTPSSL=1', 'timeout':3, 'end': 'OK'},
                    'disablessl': {'string':'AT+HTTPSSL=0', 'timeout':3, 'end': 'OK'},
                    'initurl':    {'string':'AT+HTTPPARA="URL","{}"'.format(data), 'timeout':3, 'end': 'OK'},
                    'doget':      {'string':'AT+HTTPACTION=0', 'timeout':3, 'end': '+HTTPACTION'},
                    'setcontent': {'string':'AT+HTTPPARA="CONTENT","{}"'.format(data), 'timeout':3, 'end': 'OK'},
                    'postlen':    {'string':'AT+HTTPDATA={},5000'.format(data), 'timeout':3, 'end': 'DOWNLOAD'},  # "data" is data_lenght in this context, while 5000 is the timeout
                    'dumpdata':   {'string':data, 'timeout':1, 'end': 'OK'},
                    'dopost':     {'string':'AT+HTTPACTION=1', 'timeout':3, 'end': '+HTTPACTION'},
                    'getdata':    {'string':'AT+HTTPREAD', 'timeout':3, 'end': 'OK'},
                    'closehttp':  {'string':'AT+HTTPTERM', 'timeout':3, 'end': 'OK'},
                    'closebear':  {'string':'AT+SAPBR=0,1', 'timeout':3, 'end': 'OK'}
        }

        # References:
        # https://github.com/olablt/micropython-sim800/blob/4d181f0c5d678143801d191fdd8a60996211ef03/app_sim.py
        # https://arduino.stackexchange.com/questions/23878/what-is-the-proper-way-to-send-data-through-http-using-sim908
        # https://stackoverflow.com/questions/35781962/post-api-rest-with-at-commands-sim800
        # https://arduino.stackexchange.com/questions/34901/http-post-request-in-json-format-using-sim900-module (full post example)

        # Sanity checks
        if command not in commands:
            raise Exception('Unknown command "{}"'.format(command))

        # Support vars
        command_string  = commands[command]['string']
        expected_end   = commands[command]['end']
        timeout         = commands[command]['timeout']
        #processed_lines = 0

        # Execute the AT command
        command_string_for_at = "{}\r\n".format(command_string)
        logger.debug('Writing AT command "{}"'.format(command_string_for_at.encode('utf-8')))
        self.uart.write(command_string_for_at)

        if yield_buf:
            return self.read_at_response(command_string, expected_end, timeout, buf_size, binary_output)
        output = b'' if binary_output else '' 
        for buf in self.read_at_response(command_string, expected_end, timeout, buf_size, binary_output):
            output += buf
        # Remove the command string from the output
        #output = output.replace(command_string+'\r\r\n', '')

        # ..and remove the last \r\n added by the AT protocol
        if output.endswith('\r\n'):
            output = output[:-2]

        # Also, clean output if needed
        if clean_output:
            output = output.replace('\r', '')
            output = output.replace('\n\n', '')
            if output.startswith('\n'):
                output = output[1:]
            if output.endswith('\n'):
                output = output[:-1]

        logger.debug('Returning "{}"'.format(output.encode('utf8')))

        # Return
        return output

    def read_at_response(self, command_string, expected_end, timeout, buf_size=None, binary_output=False):
        # Support vars
        prev_line = b''

        def read_line():
            empty_reads = 0
            line = self.uart.read(buf_size) if buf_size else self.uart.readline()
            logger.debug('Read "{}"'.format(line))
            if not line:
                time.sleep(1)
                empty_reads += 1
                if empty_reads > timeout:
                    if buf_size:
                        return line
                    else:
                        raise ReadTimeoutException()
            return line

        line = read_line().replace(bytes(command_string, 'utf-8') + b'\r\r\n', b'')
        
        while True:
            break_flag = False
            test_line = prev_line + line
            # Do we have an error?
            if b'ERROR\r\n' in test_line:
                raise GenericATError('Got generic AT error')

                # If we had a pre-end, do we have the expected end?
            if test_line.endswith(bytes(expected_end, 'utf-8') + b'\r\n'):
                logger.debug('Detected exact end')
                line = line.replace(bytes(expected_end, 'utf-8') + b'\r\n', b'')
                break_flag = True
            if b'\r\n' + bytes(expected_end, 'utf-8') in test_line:
                logger.debug('Detected startwith end (and adding this line to the output too)')
                break_flag = True

            if command_string == 'AT+HTTPREAD' and b'+HTTPREAD:' in line:
                line = re.sub(b'\+HTTPREAD: \d+\r\n', b'', line)
                
            yield line if binary_output else line.decode('utf-8')

            if break_flag:
                break

            prev_line = line
            line = read_line()
            if not line:
                line = b''



    #----------------------
    #  Function commands
    #----------------------

    def get_info(self):
        output = self.execute_at_command('modeminfo')
        return output

    def battery_status(self):
        output = self.execute_at_command('battery')
        return output

    def scan_networks(self):
        networks = []
        output = self.execute_at_command('scan')
        pieces = output.split('(', 1)[1].split(')')
        for piece in pieces:
            piece = piece.replace(',(','')
            subpieces = piece.split(',')
            if len(subpieces) != 4:
                continue
            networks.append({'name': json.loads(subpieces[1]), 'shortname': json.loads(subpieces[2]), 'id': json.loads(subpieces[3])})
        return networks

    def get_current_network(self):
        output = self.execute_at_command('network')
        network = output.split(',')[-1]
        if network.startswith('"'):
            network = network[1:]
        if network.endswith('"'):
            network = network[:-1]
        # If after filtering we did not filter anything: there was no network
        if network.startswith('+COPS'):
            return None
        return network

    def get_signal_strength(self):
        # See more at https://m2msupport.net/m2msupport/atcsq-signal-quality/
        output = self.execute_at_command('signal')
        signal = int(output.split(':')[1].split(',')[0])
        signal_ratio = float(signal)/float(30) # 30 is the maximum value (2 is the minimum)
        return signal_ratio

    def get_ip_addr(self):
        output = self.execute_at_command('getbear')
        output = output.split('+')[-1] # Remove potential leftovers in the buffer before the "+SAPBR:" response
        pieces = output.split(',')
        if len(pieces) != 3:
            raise Exception('Cannot parse "{}" to get an IP address'.format(output))
        ip_addr = pieces[2].replace('"','')
        if len(ip_addr.split('.')) != 4:
            raise Exception('Cannot parse "{}" to get an IP address'.format(output))
        if ip_addr == '0.0.0.0':
            return None
        return ip_addr

    def connect(self, apn, user='', pwd=''):
        if not self.initialized:
            raise Exception('Modem is not initialized, cannot connect')

        # Are we already connected?
        if self.get_ip_addr():
            logger.debug('Modem is already connected, not reconnecting.')
            return

        # Closing bearer if left opened from a previous connect gone wrong:
        logger.debug('Trying to close the bearer in case it was left open somehow..')
        try:
            self.execute_at_command('closebear')
        except GenericATError:
            pass

        # First, init gprs
        logger.debug('Connect step #1 (initgprs)')
        self.execute_at_command('initgprs')

        # Second, set the APN
        logger.debug('Connect step #2 (setapn)')
        self.execute_at_command('setapn', apn)
        self.execute_at_command('setuser', user)
        self.execute_at_command('setpwd', pwd)

        # Then, open the GPRS connection.
        logger.debug('Connect step #3 (opengprs)')
        self.execute_at_command('opengprs')

        # Ok, now wait until we get a valid IP address
        retries = 0
        max_retries = 5
        while True:
            retries += 1
            ip_addr = self.get_ip_addr()
            if not ip_addr:
                retries += 1
                if retries > max_retries:
                    raise Exception('Cannot connect modem as could not get a valid IP address')
                logger.debug('No valid IP address yet, retrying... (#')
                time.sleep(1)
            else:
                break

    def disconnect(self):

        # Close bearer
        try:
            self.execute_at_command('closebear')
        except GenericATError:
            pass

        # Check that we are actually disconnected
        ip_addr = self.get_ip_addr()
        if ip_addr:
            raise Exception('Error, we should be disconnected but we still have an IP address ({})'.format(ip_addr))


    def http_request(self, url, mode='GET', data=None, content_type='application/json', buf_size=None, yield_buf=False, binary_output=False):

        # Protocol check.
        assert url.startswith('http'), 'Unable to handle communication protocol for URL "{}"'.format(url)

        # Are we  connected?
        if not self.get_ip_addr():
            raise Exception('Error, modem is not connected')

        # Close the http context if left open somehow
        logger.debug('Close the http context if left open somehow...')
        try:
            self.execute_at_command('closehttp')
        except GenericATError:
            pass

        # First, init and set http
        logger.debug('Http request step #1.1 (inithttp)')
        self.execute_at_command('inithttp')
        logger.debug('Http request step #1.2 (sethttp)')
        self.execute_at_command('sethttp')

        # Do we have to enable ssl as well?
        if self.ssl_available:
            if url.startswith('https://'):
                logger.debug('Http request step #1.3 (enablessl)')
                self.execute_at_command('enablessl')
            elif url.startswith('http://'):
                logger.debug('Http request step #1.3 (disablessl)')
                self.execute_at_command('disablessl')
        else:
            if url.startswith('https://'):
                raise NotImplementedError("SSL is only supported by firmware revisions >= R14.00")

        # Second, init and execute the request
        logger.debug('Http request step #2.1 (initurl)')
        self.execute_at_command('initurl', data=url)

        if mode == 'GET':

            logger.debug('Http request step #2.2 (doget)')
            output = self.execute_at_command('doget')
            response_status_code = output.split(',')[1]
            logger.debug('Response status code: "{}"'.format(response_status_code))

        elif mode == 'POST':

            logger.debug('Http request step #2.2 (setcontent)')
            self.execute_at_command('setcontent', content_type)

            logger.debug('Http request step #2.3 (postlen)')
            self.execute_at_command('postlen', len(data))

            logger.debug('Http request step #2.4 (dumpdata)')
            self.execute_at_command('dumpdata', data)

            logger.debug('Http request step #2.5 (dopost)')
            output = self.execute_at_command('dopost')
            logger.debug('Http output: "{}"'.format(output))
            response_status_code = output.split(',')[1]
            logger.debug('Response status code: "{}"'.format(response_status_code))


        else:
            raise Exception('Unknown mode "{}'.format(mode))

        # Third, get data
        logger.debug('Http request step #4 (getdata)')
        response_content = self.execute_at_command('getdata', clean_output=False, buf_size=buf_size, yield_buf=yield_buf)

        if yield_buf:
            return response_content

        logger.debug(response_content)

        # Then, close the http context
        logger.debug('Http request step #4 (closehttp)')
        self.execute_at_command('closehttp')

        return Response(status_code=response_status_code, content=response_content)
