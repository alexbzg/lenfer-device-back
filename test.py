from SIM800L import Modem
from utils import load_json
from time import sleep

def create_m():
    c = load_json('conf.json')
    m = Modem(**c['gsm_modem']['pins'])
    m.initialize()
    sleep(1)
    #print('Modem info: "{}"'.format(m.get_info()))
    #print('Network scan: "{}"'.format(m.scan_networks()))
    #print('Current network: "{}"'.format(m.get_current_network()))
    #print('Signal strength: "{}%"'.format(m.get_signal_strength()*100))

    m.connect(**c['gsm_modem']['apn'])
    return m