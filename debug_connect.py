import network

def connect():

    nic = network.WLAN(network.STA_IF)
    nic.active(True)
    nic.connect('R7AB_office', '18231824')
