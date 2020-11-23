from mininet.net import Mininet
from mininet.node import Controller, OVSKernelSwitch, RemoteController
from mininet.cli import CLI
from mininet.link import TCLink
from mininet.log import setLogLevel, info, debug
import random
import ipaddress
import yaml 
import os

# NOTE: debugger
#import code; code.interact(local=dict(globals(), **locals()))

class MininetSDN:
    SUBNET = ipaddress.ip_network(unicode('10.42.0.0/24'))
    POX_PORT = 6633
    LINK_COUNT = 6  # I'm hard coding this because I have brain damage
    net = None

    def __init__(self):
        self.net = self.setup_network()
        self.hosts = self.setup_hosts(8)
        self.switches = self.setup_switches(4)
        self.setup_links()
        #self.SPIN_THAT_WHEEL()

        self.start_network()

    def setup_network(self):
        net = Mininet(controller=RemoteController, ipBase=str(self.SUBNET), link=TCLink)
        c1 = net.addController('c1', controller=RemoteController, port=self.POX_PORT)
        return net
        
    def setup_hosts(self, count):
        hosts = []
        for i in range(0,count):
            # We need to add +1 to the host variable because arrays start at 0
            n = i+1
            new_host = self.net.addHost(name="h"+str(n), ip=str(self.SUBNET[n]), mac="00:00:00:00:00:0"+str(n))
            self.goodbye_ipv6(new_host)
            hosts.append(new_host)
        return hosts

    def setup_switches(self, count):
        switches = []
        for i in range(0,4):
            new_switch = self.net.addSwitch('s'+str(i+1))
            self.goodbye_ipv6(new_switch)
            switches.append(new_switch)
        return switches
    
    def setup_links(self):
        # We can safely assume that links.yml is accessible in the current directory
        with open("links.yml", 'r') as fp:
            try: 
                links = yaml.safe_load(fp) # safe_load is apparently preferred, if it encounters any issues in the file formatting, it'll throw an exception
            except yaml.YAMLError as exc:
                print(exc)
                os.exit(1)
            finally:
                fp.close()
 
        for src in links:
            src_obj = self.get_network_obj(src, "switch")

            connections = links[src]
            for dst in connections:
                src_port = int(connections[dst])
                try:
                    dst_port = links[dst][src]
                    # This variable only gets set if setting dst_port doesn't throw a KeyError exception; dst_obj will be another switch
                    dst_obj = self.get_network_obj(dst, "switch")
                    self.add_link(src_obj, src_port, dst_obj, dst_port)
                except KeyError:
                    # This means we hit a host and not a switch, so that means our destination port will always be 1 (see "1" being set as the second arg in add_link below)
                    host_obj = self.get_network_obj(dst, "host")
                    self.add_link(host_obj, 1, src_obj, src_port)
    
    def get_network_obj(self, name, obj_type):
        if obj_type == "switch":
            return self.switches[int(name[-1])-1]
        elif obj_type == "host":
            return self.hosts[int(name[-1])-1]

    def add_link(self, conn1, port1, conn2, port2):
        try:
            #delay = str(random.randint(10,250)) + "ms"
            # NOTE: TEMP
            #delay = str(random.randint(200,250)) + "ms"

            #self.net.addLink(conn1, conn2, port1=port1, port2=port2, bw=100, delay=delay)
            self.net.addLink(conn1, conn2, port1=port1, port2=port2, bw=100)
        except Exception as e: # Mininet only throws "Exception" type exceptions. We can narrow this down, however.
            if "File exists" in str(e):
                # We hit this point if the link already exists. Just skip it.
                pass
            else:
                print("WHOOPS! Something reaaaaaally bad happened. Here's what Python is complaining about:")
                print(str(e))
                os.exit(1)
    
    def goodbye_ipv6(self, host):
        # IPv6 is good until it impedes my ability to finish work
        host.cmd("sysctl -w net.ipv6.conf.all.disable_ipv6=1")
        host.cmd("sysctl -w net.ipv6.conf.default.disable_ipv6=1")
        host.cmd("sysctl -w net.ipv6.conf.lo.disable_ipv6=1")

    def SPIN_THAT_WHEEL(self):
        # Randomly give a link a lot of delay
        print("\n\n")
        # Pick 2 random switches
        sw1, sw2 = random.sample(self.switches, 2)
        linky = [link for link in self.net.links if (sw1, sw2) in ((link.intf1.node, link.intf2.node), (link.intf2.node, link.intf1.node))][0]
        print("UH OH! Looks like link " + str(linky) + " was naughty and was given a punishment of 500 ms of delay!")
        self.net.delLink(linky)
        #import code; code.interact(local=dict(globals(), **locals()))
        #linky.intf1.config(latency_ms="500")
        #linky.intf2.config(latency_ms="500")
        
    def start_network(self):
        self.net.build()
        self.net.start()
        CLI(self.net)
        self.net.stop()
    
if __name__ == '__main__': 
    setLogLevel('info')
    mn = MininetSDN()
