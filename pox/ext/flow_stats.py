from pox.core import core
from pox.lib.util import dpidToStr, strToDPID
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
SPATHS = {} # TODO: Find a way to efficiently store shortest paths in a variable

# Referenced from here:
# https://upcommons.upc.edu/bitstream/handle/2117/79127/109527.pdf
class LittlePacket(packet_base):
    def __init__(self):
        packet_base.__init__(self)
        self.timestamp=0

        def hdr(self, payload):
            return struct.pack('!I', self.timestamp)

def _handle_connectionup(event):
    global g
    # Add a node to the networkx graph and assign it an identifiable name
    sw_name = "sw" + str(event.dpid)
    g.add_node(dpidToStr(event.dpid), name=sw_name, node_type="switch")
    if g.nodes.get(dpidToStr(event.dpid)):
        g.nodes[dpidToStr(event.dpid)]['connection'] = event.connection

    # Install a flow rule on the switch that allows for broadcast traffic
    # Match ethernet traffic with dst ff:ff:ff:ff:ff:ff, flood all ports
    # Take NOTE: we rely on the spanning tree module to prevent broadcasts out any non-root ports to prevent broadcast storms
    msg = of.ofp_flow_mod()
    msg.match.dl_dst = EthAddr("ff:ff:ff:ff:ff:ff") #broadcast
    msg.actions = [of.ofp_action_output(port=of.OFPP_FLOOD), of.ofp_action_output(port=of.OFPP_CONTROLLER)] #flood out all ports except incoming port and send to controller for topology learning
    event.connection.send(msg)

    # When all switches are up, start the timer that runs the delay calculations
    #print(nx.number_of_nodes(g))
    #if nx.number_of_nodes(g) == 4:
    #    log.info("All switches up, starting delay calculation timer")
    #    _get_switch_peer_ports()
    #    Timer(5, _timer_func, recurring=True) 

# Generates a list of either hosts or switches
def _generate_nx_list(node_type):
    global g
    node_list = []
    for node in g.nodes(data=True):
        if node[1]['node_type'] == node_type:
            # Append a tuple containing the node's ID and the name attribute
            node_list.append((node[0], node[1]['name']))
    return node_list

def _timer_func ():
    peer_list = _get_switch_peer_ports()
    #for switch in peer_list:
 
def _calculate_delay():
    pass

def _get_switch_peer_ports():
    global g
    
    switches = _generate_nx_list("switch")
    peer_list = {}
    for switch in switches:
        sw_nx_id = switch[0]
        edges = g.edges([sw_nx_id])   # Edging da switches
        edge_list = []
        for edge in edges:
            peer_nx_id = edge[1]
            edge_attrs = g.get_edge_data(sw_nx_id, peer_nx_id) 
            edge_list.append((edge_attrs['ports'][sw_nx_id], peer_nx_id)) # A tuple containing the port on the switch where peer_nx_id can be found
        peer_list[sw_nx_id] = edge_list
    return peer_list

def _calculate_shortest_paths():
    global g
    hosts = _generate_nx_list("host")
    if hosts:
        for h in hosts:
            other_hosts = hosts[:]  # Create a clone of the existing hosts list, but very fastly (according to https://stackoverflow.com/a/26875847)
            other_hosts.remove(h)   # We're essentially creating a list that contains all hosts EXCEPT what is currently "h"
            # WE HAVE TO GO DEEPER
            # BIG O TIME IS A PSYOP MEANT TO HOLD BACK PROGRAMMERS
            # TAKE NOTE!
            for o in other_hosts:
                spath = nx.dijkstra_path(g, source=h[0], target=o[0])
                print("#### BEST PATH FOR " + str(h[1]) + " -> " + str(o[1]))
                print(spath)
                _generate_flow_rules(spath)

# When da switches do da linky
def _handle_linkevent(event):
    l = event.link
    dpid1 = dpidToStr(l.dpid1)
    dpid2 = dpidToStr(l.dpid2)
    
    # Check if the edge exists first - networkx WILL try to add the edge again if you don't check
    if not _edge_exists(dpid1, dpid2):
        _add_graph_edge(dpid1, dpid2, l.port1, l.port2, "switch") 

def _add_graph_edge(peer1, peer2, port1, port2, link_type):
    global g

    ports = _generate_port_dict(peer1, peer2, port1, port2)
    if link_type == "switch":
        # All switch-switch edges are initialized with a weight of 1.0. This weight value will be adjusted for delay calculations
        g.add_edge(peer1, peer2, ports=ports, weight=1.0, link_type="switch")
        _gen_link_state_log(peer1, peer2, "Adding new switch-switch edge to graph")
    elif link_type == "host":
        # No weights are needed for host-switch links
        g.add_edge(peer1, peer2, ports=ports, link_type="host")
        _gen_link_state_log(peer1, peer2, "Adding new host-switch edge to graph")

def _generate_port_dict(peer1, peer2, port1, port2):
    return {peer1: port1, peer2: port2}

def _get_node_by_nx_id(node_id):
    global g
    return [node for node in g.nodes(data=True) if node[0] == node_id]
  
def _generate_flow_rules(path, packet_event, sw_dpid):
    """ 
    Inputs:
    path - a list of nodes representing the path selected between two hosts
        for example, ['00:00:00:00:00:02', '00-00-00-00-00-01', '00-00-00-00-00-04', '00:00:00:00:00:07']

    Function will dynamically create rules to enable each hop in the given path and install those rules on all switches in path

    Returns: N/A
    """
    log.info("A packet! Is for me? 🥺 👉👈")
    #A path should always start with a host and end with a host, with switches in between
    #Validate that the given path follows this format
    source_mac = path[0]
    dest_mac = path[-1]
    
    if not g.nodes.get(source_mac) or g.nodes.get(source_mac).get('node_type') != "host":
        log.error(source_mac+" is not of type host source mac; _generate_flow_rules cannot install flows")
        return
    if not g.nodes.get(dest_mac) or g.nodes.get(dest_mac).get('node_type') != "host":
        log.error(dest_mac+" is not of type host dest mac; _generate_flow_rules cannot install flows")
        return

    #Remove the source and destination hosts from the path
    path = path[1:]
    #for each hop in the path...
    for source, dest in zip(path, path[1:]):
        edge = g.edges.get((source,dest)) #get the edge between the two switches
        if edge:
            output_port = edge.get('ports').get(source)
            
            # Generate a packet_out to tell the switch where to send the packet
            msg = of.ofp_packet_out()
            msg.data = packet_event.data
            msg.in_port = packet_event.port
            msg.actions.append(of.ofp_action_output(port=output_port))
            g.nodes.get(sw_dpid).get('connection').send(msg)
            log.info("Packet out! Is for you! 😏👈👈")
            
            # Install a flow that helps the dumb dumb switch know where to send similar packets 
            msg = of.ofp_flow_mod()
            msg.match.dl_src = EthAddr(source_mac)
            msg.match.dl_dst = EthAddr(dest_mac)
            msg.hard_timeout = 30
            msg.idle_timeout = 10
            msg.actions = [of.ofp_action_output(port=output_port)]
            if g.nodes.get(source):
                g.nodes.get(source).get('connection').send(msg)
                log.info("Installed flow for " +source_mac+"->"+dest_mac+" on "+source)
            else:
                log.error("Failed to install flow for "+source_mac+"->"+dest_mac+" on "+source)

def _handle_packetin(event):
    global g
    packet = event.parsed
    
    host_mac = str(packet.src)
    host_name = "h" + str(host_mac[-1])
    
    # If we don't get a result back for this, this means there's no node for this host yet
    if not _get_node_by_nx_id(host_mac):
        g.add_node(host_mac, name=host_name, node_type="host")

    sw_port = event.port
    sw_dpid = dpidToStr(event.dpid)
    
    # Host nodes should only have an edge added if they don't have any edges. Hosts can only have 1 edge, which will be the link to their switch
    if len(g.edges([host_mac])) == 0:
        # We need this method because of broadcasts - need to filter out packets we've received that appear to be sourced from a host, but come from a switch->switch link.
        if not _is_trunk_port(sw_port, sw_dpid):
            # Check if the edge exists already, if it doesn't, create it
            #if not g.has_edge(host_mac, sw_dpid):
            if not _edge_exists(host_mac, sw_dpid):
                # "0" is the host's port; this will always be 0
                _add_graph_edge(host_mac, sw_dpid, 0, sw_port, "host")
    try:
        #if src and dst are in graph
        if g.nodes.get(str(packet.src)) and g.nodes.get(str(packet.dst)):
            path = nx.dijkstra_path(g, str(packet.src), str(packet.dst))
            print("Generated path ",path)
            _generate_flow_rules(path, event, sw_dpid)
    except nx.exception.NetworkXNoPath:
        log.error("Could not calculate path between "+str(packet.src)+" and "+str(packet.dst))
     

def _edge_exists(peer1, peer2):
    return g.has_edge(peer1, peer2)

def _is_trunk_port(port, dpid):
    global g
    edges = g.edges(dpid, data=True)
    for edge in edges:
        # Check if port has a match for "source" and "port1"
        if dpid == edge[0] and edge[2]['ports'][dpid] == port and edge[2]['link_type'] == "switch":
            log.warning("Found packet from trunk port of switch, ignoring")
            return True
        # Check if port has a match for "target" and "port2"
        elif dpid == edge[1] and edge[2]['ports'][dpid] == port and edge[2]['link_type'] == "switch":
            log.warning("Found packet from trunk port of switch, ignoring")
            return True
    # If we don't hit anything, we don't have a trunk port, so return False
    return False

def _gen_link_state_log(peer1, peer2, msg):
    log.info(str(peer1) + " -> " + str(peer2) + ": " + msg)
    _save_graph_json_data()

def _dump_graph_json_data():
    global g
    return json_graph.node_link_data(g)

def _save_graph_json_data():
    global g
    f = open("networkx_graph.json",'w')
    f.write(json.dumps(json_graph.node_link_data(g),indent=2,default=lambda o: '<not serializable>'))
    f.close()

def launch():
    global g
    g = nx.Graph()
    
    def start():
        core.openflow.addListenerByName("ConnectionUp", _handle_connectionup)
        core.openflow_discovery.addListenerByName("LinkEvent", _handle_linkevent)
        core.openflow.addListenerByName("PacketIn", _handle_packetin)

    core.call_when_ready(start, ('openflow', 'openflow_discovery'))
    # Timer kicks off only once everything else has started - neat!
    # By then, all the switches should be active and have all their edges set in the NX graph object
    Timer(5, _timer_func, recurring=True) 
    
# TODO:
# Add a broadcast flow rule on ConnectionUp for each switch that matches any Ethernet traffic to 255.255.255.255 with action flood
