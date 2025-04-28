

class Call:

    def __init__(self):
        self.state = "init"

    def responded(self):
        self.state = "on"
    
    def stopped(self):
        self.state = "stopped"


call = Call()
