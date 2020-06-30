import network

NETWORK_MODE = network.STA_IF

if NETWORK_MODE == network.AP_IF:
    AP = network.WLAN(network.AP_IF)
    AP.config(essid="esp32", password="123123123", authmode=4)
    AP.ifconfig(("192.168.0.1", "255.255.255.0", "192.168.0.1", "192.168.0.1"))
    AP.active(True)
else:
    nic = network.WLAN(network.STA_IF)
    nic.active(True)
    nic.connect('R7AB_office', '18231824')    
