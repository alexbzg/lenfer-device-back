class LenferController:
    def __init__(self, device, conf=None):
        self.schedule = None
        self.device = device
        self.name = conf.get('name') if conf else None

    def get_updates_props(self):
        return {}

    def update_settings(self):
        pass
