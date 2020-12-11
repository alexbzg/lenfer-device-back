class LenferController:
    def __init__(self, device):
        self.schedule = None
        self.device = device
        
    @property
    def updates_props(self):
        return {}

    @updates_props.setter
    def updates_props(self, data):
        pass
