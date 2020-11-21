from pox.core import core
from pox.lib.util import dpidToStr
import pox.openflow.libopenflow_01 as of
from pox.openflow.of_json import *
from pox.lib.recoco import Timer
from pox.lib.packet.packet_base import packet_base
from pox.lib.packet.packet_utils import *
#from pox.openflow.discovery import LinkEvent, DiscoveryGraph, graph
#from pox.openflow.spanning_tree import _calc_spanning_tree
import json
import time
import struct
import networkx as nx
from networkx.readwrite import json_graph

log = core.getLogger()

# networkx graph object init
g = None

# The maximum amount of acceptable delay (in ms) on a link - anything above this will result in the link being less optimal
DELAY_CAP = 200

def _handle_connectionup(event):
    global g
    # Add a node to the networkx graph and assign it an identifiable name
    sw_name = "sw" + str(event.dpid)
    g.add_node(event.dpid, name=sw_name)

# Generate a list of *host* node IDs in the NX graph
def _generate_nx_host_list():
    global g
    host_list = []
    for node in g.nodes(data=True):
        print(node)
       #if node[1]:
       #    host_list.append(node[0])
    return host_list

# Generate a list of *switch* node IDs in the NX graph
def _generate_nx_switch_list():
    global g
    switch_list = []
    # TODO: Not.... this. This is really fucking redundant. Try to find a way to merge this with the above method because I AM NOT HAVING THIS
    for node in g.nodes(data="host_mac"):
        if not node[1]:
            switch_list.append(node[0])

def _timer_func ():
    global g
    hosts = _generate_nx_host_list()
    print(hosts)
    '''
    if hosts:
        for h in hosts:
            other_hosts = hosts[:]  # Create a clone of the existing hosts list, but very fastly (according to https://stackoverflow.com/a/26875847)
            other_hosts.remove(h)   # We're essentially creating a list that contains all hosts EXCEPT what is currently "h"
            # WE HAVE TO GO DEEPER
            # BIG O TIME IS A PSYOP MEANT TO HOLD BACK PROGRAMMERS
            # TAKE NOTE!
            for o in other_hosts:
                spath = nx.shortest_path(g, source=h, target=o)
                print("#### BEST PATH FOR " + str(h) + " -> " + str(o))
                print(spath)

    '''

    #nx.shortest_path(g, source=

   # for 
    #short_path = g.shortest_path(
    #for connection in core.openflow._connections.values():
        #connection.send(of.ofp_stats_request(body=of.ofp_flow_stats_request()))
        #connection.send(of.ofp_stats_request(body=of.ofp_port_stats_request()))
    #log.debug("Sent %i flow/port stats request(s)", len(core.openflow._connections))

def _handle_linkevent(event):
    l = event.link
    if event.added:
        _add_graph_edge(l.dpid1, l.dpid2, l.port1, l.port2, "switch") 
    elif event.removed:
        _set_graph_edge_state(l.dpid1, l.dpid2, state=False)

def _add_graph_edge(peer1, peer2, port1, port2, link_type):
    global g
    if link_type == "switch":
        _gen_link_state_log("sw"+str(peer1), "sw"+str(peer2), "Adding new switch-switch edge to graph")
        # Edges are initialized with zero values for usage and delay, they'll be computed later
        # state=True means the link is up
        # All switch-switch edges are initialized with a weight of 1.0. This weight value is adjusted as bandwidth and delay calculations run
        # NOTE: I'm removing the "state" arg because I don't think we'll need it
        g.add_edge(peer1, peer2, port1=port1, port2=port2, usage=0, delay=0, weight=1.0)
    elif link_type == "host":
        # PEER1 MUST BE THE HOST DO NOT MESS THIS UP
        _gen_link_state_log(peer1, peer2, "Adding new host-switch edge to graph")
        g.add_edge(peer1, peer2, port1=port1, port2=port2)

def _del_graph_edge(dpid1, dpid2):
    global g
    log.info("Removing link from graph")
    g.remove_edge(dpid1, dpid2)

# This method is invoked if we need to push a change to either the usage or delay attrs stored for the edge
#def _update_graph_edge(dpid1, dpid2, **kwargs):
#    global g
#    attrs = {(dpid1, dpid2): kwargs}
#    nx.set_edge_attributes(g, attrs)

def _set_graph_edge_state(dpid1, dpid2, state):
    global g
    g[dpid1][dpid2][0]['state'] = state
    _gen_link_state_log(dpid1, dpid2, "Updated link state in graph")
    #log.info(str(dpid1) + " -> " + str(dpid2) + ": Updated link state in graph")

#def _find_graph_node(attr, val):
#    global g
#    return any([node for node in g.nodes(data=True) if node[1][attr] == val])

def _get_node_obj_by_name(node_name):
    global g
    return [node for node in g.nodes(data="name") if node[1] == node_name]

def _get_node_by_mac_addr(node_mac):
    global g
    for node in g.nodes(data=True):
        try:
            # NOTE: Debugging
            #print(node[1])
            #print(node_mac)
            if node[1]['host_mac'] == node_mac:
                return node
        except KeyError:    # This exception is hit if we run the check above on a switch node, which doesn't have a host_mac attr
            continue
    #return [node for node in g.nodes(data=True) if node[1]['host_mac'] == node_mac]

def _drop_packet_handler(packet):
    msg = of.ofp_flow_mod()
    msg.match = of.ofp_match.from_packet(packet)
    msg.buffer_id = event.ofp.buffer_id
    print(msg)
    self.connection.send(msg)


def _handle_packetin(event):
    global g
    packet = event.parsed
    print("===PACKET===")
    print(packet)
    print(packet.src)
    print("============")
    #if packet.type == packet.LLDP_TYPE or packet.dst.isBridgeFiltered():
    #    _drop_packet_handler(packet)
    
    host_src_mac = str(packet.src)
    host_id = host_src_mac[-1]      # This should not be passed into networkx, this is JUST for getting the name of the node (which corresponds to MAC address)
    host_name = "h" + str(host_id)
   
    node_obj = _get_node_obj_by_name(host_name)
    print(node_obj)
    # If we don't get a result back for this, this means there's no node for this host yet
    if not node_obj:
        # Since we need to provide an ID for each node, we can just increment the number of nodes by 1 to get a unique ID
        host_node_id = g.number_of_nodes() + 1
        g.add_node(host_node_id, name=host_name, host_mac=host_src_mac)
    else:
        host_node_id = node_obj[0][0]

    # Now that we either added a new host node or confirmed it already exists... let's check for edges in the graph
    host_port = 0 # This will ALWAYS be zero; hosts connect to switches via port 0
    switch_port = event.port # We can grab this info from the event object
    sw_dpid = event.dpid

    # Add an edge between the host and the switch if it doesn't exist already
    if not g.has_edge(host_node_id, sw_dpid):
    #    # NOTE: host_node_id MUST be the first arg here
        _add_graph_edge(host_node_id, sw_dpid, host_port, switch_port, "host")
     
    #packet_dst = packet.dst

    #of.ofp_packet_out()

    #if packet_dst == "ff:ff:ff:ff:ff:ff": # If broadcast, flooooooooooooooooooooood
    #    log.info("Flooding packet")
    #    msg = of.ofp_packet_out()
    #    msg.actions.append(of.ofp_action_output(port = of.OFPP_FLOOD))
    #    msg.data = event.ofp
    #    msg.in_port = event.port
    #    event.connection.send(msg)

    #print(_get_node_by_mac_addr(packet_dst))


    #if packet.dst not in 
    #print(packet_dst)

    
    #in_port = event.ofp.in_port
    #if in_port 
    #rt
    #print(vars(g))
    #msg = of.ofp_packet_out(data=event.ofp)
    #print(msg)

def _gen_link_state_log(peer1, peer2, msg):
    log.info(str(peer1) + " -> " + str(peer2) + ": " + msg)

#def _get_link_delay():

def _dump_graph_json_data():
    global g
    print(json.dumps(json_graph.node_link_data(g),indent=2))

def launch():
    global g
    #g = nx.MultiDiGraph()
    g = nx.Graph()
    
    def start():
        core.openflow.addListenerByName("ConnectionUp", _handle_connectionup)
        core.openflow_discovery.addListenerByName("LinkEvent", _handle_linkevent)
        core.openflow.addListenerByName("PacketIn", _handle_packetin)
        Timer(5, _timer_func, recurring=True)
    core.call_when_ready(start, ('openflow', 'openflow_discovery'))

# TODO:
# Add a broadcast flow rule on ConnectionUp for each switch that matches any Ethernet traffic to 255.255.255.255 with action flood
