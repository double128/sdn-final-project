from mininet.net import Mininet
from mininet.node import Controller, OVSKernelSwitch, RemoteController
from mininet.cli import CLI
from mininet.link import TCLink
from mininet.log import setLogLevel, info, debug
import ipaddress
 
# NOTE: debugger
#import code; code.interact(local=dict(globals(), **locals()))

class MininetSDN:
    net = None
    controller_1 = None

    SUBNET = ipaddress.ip_network(unicode('10.42.0.0/24'))
    POX_PORT = 6633

    def __init__(self):
        self.net = self.setup_network()
        
        hosts = self.setup_hosts(8)
        switches = self.setup_switches(4)
        
        # Adding switch connections manually... I will loop this later
        
        # S1 P1 -> S2 P1
        self.add_link(switches[0], 1, switches[1], 1)

        # S1 P2 -> S3 P1
        self.add_link(switches[0], 2, switches[2], 1)

        # S1 P3 -> S4 P1
        self.add_link(switches[0], 3, switches[3], 1)

        # S2 P2 -> S3 P2 
        self.add_link(switches[1], 2, switches[2], 2)

        # S2 P3 -> S4 P2 
        self.add_link(switches[1], 3, switches[3], 2)

        # S3 P3 -> S4 P3 
        self.add_link(switches[2], 3, switches[3], 3)

        c = 0
        for x in switches:
            ### for later ;-)
            ###other_switches = [j for i,j in enumerate(switches) if i!=int(x.name[-1])]
            ###for o in other_switches:
            self.add_link(hosts[c], 1, x, 4)
            self.add_link(hosts[c+1], 1, x, 5)
            c = c + 2
        
        self.start_network()

    def setup_network(self):
        net = Mininet(controller=RemoteController, ipBase=str(self.SUBNET), link=TCLink)
        c1 = net.addController('c1', controller=RemoteController, port=self.POX_PORT)
        return net
        
    def setup_hosts(self, count):
        hosts = []
        for i in range(0,8):
            # We need to add +1 to the host variable because arrays start at 0
            n = i+1
            hosts.append(self.net.addHost(name="h"+str(n), ip=str(self.SUBNET[n]), mac="00:00:00:00:00:0"+str(n)))
        return hosts

    def setup_switches(self, count):
        switches = []
        for i in range(0,4):
            switches.append(self.net.addSwitch('s'+str(i+1)))
        return switches

    def add_link(self, conn1, port1, conn2, port2):
        self.net.addLink(conn1, conn2, port1=port1, port2=port2)

    def start_network(self):
        self.net.build()
        self.net.start()
        #self.net.staticArp()
        CLI(self.net)
        self.net.stop()
    
if __name__ == '__main__': 
    setLogLevel('info')
    mn = MininetSDN()
