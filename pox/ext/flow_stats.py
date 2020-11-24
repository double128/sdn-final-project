from pox.core import core
from pox.lib.util import dpidToStr, strToDPID
import pox.openflow.libopenflow_01 as of
from pox.openflow.of_json import *
from pox.lib.recoco import Timer
from pox.lib.packet.packet_base import packet_base
from pox.lib.packet.packet_utils import *
import pox.lib.packet as pkt
import json
import time
import struct
import networkx as nx
from networkx.readwrite import json_graph

log = core.getLogger()

g = None            # networkx graph object goes here
DELAY_CAP = 50     # The maximum acceptable delay on a switch-switch link (in ms)
ETHERTYPE = 0x809B  # This is AppleTalk. Nothing uses AppleTalk anymore. If you own something that does, please consult a physician
MODULE_START = 0    # When the module first started running

# Referenced from here:
# https://upcommons.upc.edu/bitstream/handle/2117/79127/109527.pdf
class LittlePacket(packet_base):
    def __init__(self):
        packet_base.__init__(self)
        self.timestamp = 0

    def hdr(self, payload):
        return struct.pack('!I', int(self.timestamp))


##############################################
#             EVENT HANDLERS                 #
##############################################

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

# When da switches do da linky
def _handle_linkevent(event):
    l = event.link
    dpid1 = dpidToStr(l.dpid1)
    dpid2 = dpidToStr(l.dpid2)
    
    if event.added:
        _add_graph_edge(dpid1, dpid2, l.port1, l.port2, "switch") 
    elif event.removed:
        _del_graph_edge(dpid1, dpid2)
    
def _handle_packetin(event):
    global g
    packet = event.parsed
    sw_port = event.port
    sw_dpid = dpidToStr(event.dpid)
    
    # If we received a delay probe packet
    if packet.type == ETHERTYPE:
        log.debug("Delay probe was received on " + sw_dpid + "." + str(sw_port))
        recv_time = time.time() * 1000 - MODULE_START
        
        c = packet.find('ethernet').payload
        d, = struct.unpack('!I', c)
        delay = recv_time - d
        weight = delay/DELAY_CAP

        if weight >= 1.0:
            try:
                bad_edge = [edge for edge in g.in_edges(sw_dpid,data=True) if sw_dpid in edge[2]['ports'] and edge[2]['ports'][sw_dpid] == sw_port][0]
                src = bad_edge[0]
                dst = bad_edge[1]
                g[src][dst][0]['weight'] = weight
                #print(g.get_edge_data(src, dst))
                log.info("Adjusted weight of link " + str(src) + " -> " + str(dst) + " to " + str(weight) + ", link exceeded maximum acceptable delay")
            except IndexError: # Gets thrown if delay is high and the link hasn't been created yet in NX
                pass
        else:
            bad_edge = [edge for edge in g.in_edges(sw_dpid,data=True) if sw_dpid in edge[2]['ports'] and edge[2]['ports'][sw_dpid] == sw_port][0]
            src = bad_edge[0]
            dst = bad_edge[1]
            if g[src][dst][0]['weight'] > 0:
                g[src][dst][0]['weight'] = 0
                log.info("Adjusted weight of link " + str(src) + " -> " + str(dst) + "back to normal")


    # If we receive any other packet that isn't a delay probe
    else:
        host_mac = str(packet.src)
        host_name = "h" + str(host_mac[-1])
        
        # If we don't get a result back for this, this means there's no node for this host yet
        if not _get_node_by_nx_id(host_mac):
            g.add_node(host_mac, name=host_name, node_type="host")
    
        # Host nodes should only have an edge added if they don't have any edges. Hosts can only have 1 edge, which will be the link to their switch
        if len(g.edges([host_mac])) == 0:
            # We need this method because of broadcasts - need to filter out packets we've received that appear to be sourced from a host, but come from a switch->switch link.
            if not _is_trunk_port(sw_port, sw_dpid):
                # Check if the edge exists already, if it doesn't, create it
                #if not g.has_edge(host_mac, sw_dpid):
                if not _edge_exists(host_mac, sw_dpid):
                    # "0" is the host's port; this will always be 0
                    # We also create a second "inverse" link since this is a directed graph and we need to know how to traverse the graph from switch->host
                    _add_graph_edge(host_mac, sw_dpid, 0, sw_port, "host")
                    _add_graph_edge(sw_dpid, host_mac, sw_port, 0, "host")
        try:
            #if src and dst are in graph
            if g.nodes.get(str(packet.src)) and g.nodes.get(str(packet.dst)):
                #path = nx.dijkstra_path(g, str(packet.src), str(packet.dst), weight='weight')
                path = nx.shortest_path(g, source=str(packet.src), target=str(packet.dst), weight='weight')
                log.info("Generated path: " + str(path))
                _generate_flow_rules(path, event, sw_dpid)
        except nx.exception.NetworkXNoPath as e:
            log.error("Could not calculate path between "+str(packet.src)+" and "+str(packet.dst)+": "+str(e))


##############################################
#                FLOW RULES                  #
##############################################

def _generate_flow_rules(path, packet_event, sw_dpid):
    """ 
    Inputs:
    path - a list of nodes representing the path selected between two hosts
        for example, ['00:00:00:00:00:02', '00-00-00-00-00-01', '00-00-00-00-00-04', '00:00:00:00:00:07']

    Function will dynamically create rules to enable each hop in the given path and install those rules on all switches in path

    Returns: N/A
    """
    log.info("A packet from " + str(sw_dpid) + "! Is for me? 🥺 👉👈")
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
        edge = g.edges.get((source,dest,0)) #get the edge between the two switches
        if edge:
            output_port = edge.get('ports').get(source)
            
            # Generate a packet_out to tell the switch where to send the packet
            msg = of.ofp_packet_out()
            msg.data = packet_event.data
            msg.in_port = packet_event.port
            msg.actions.append(of.ofp_action_output(port=output_port))
            g.nodes.get(sw_dpid).get('connection').send(msg)
            log.debug("Packet is for you " + str(sw_dpid) + "! 😏👈👈")
            
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


##############################################
#                   TIMER                    #
##############################################

def _timer_func ():
    _send_delay_probes()

def _send_delay_probes():
    global MODULE_START

    nodes = [node for node in g.nodes(data=True) if node[1]['node_type'] == "switch"]
    for n in nodes:
        source_dpid = n[0]
        node_edges = g.edges(source_dpid)
        for e in node_edges:
            out_port = g.get_edge_data(e[0], e[1])[0]['ports'][source_dpid]
            
            probe = LittlePacket()
            probe.timestamp = int(time.time()*1000 - MODULE_START)
            e = pkt.ethernet()
            e.type = ETHERTYPE  
            e.payload = probe
            msg = of.ofp_packet_out()
            msg.data = e.pack()
            msg.actions.append(of.ofp_action_output(port=out_port))
            g.nodes.get(source_dpid).get('connection').send(msg)


##############################################
#              HELPER METHODS                #
##############################################

def _add_graph_edge(source, target, port1, port2, link_type):
    global g

    ports = _generate_port_dict(source, target, port1, port2)
    if link_type == "switch":
        # All switch-switch edges are initialized with a weight of 0. This weight value will be adjusted for delay calculations
        g.add_edge(source, target, ports=ports, weight=0, link_type="switch")
        _gen_link_state_log(source, target, "Adding new switch-switch edge to graph")
    elif link_type == "host":
        # No weights are needed for host-switch links
        g.add_edge(source, target, ports=ports, link_type="host")
        _gen_link_state_log(source, target, "Adding new host-switch edge to graph")

def _del_graph_edge(source, target):
    global g
    g.remove_edge(source, target)
    _gen_link_state_log(source, target, "Removing link from graph")

# Generates a list of either hosts or switches
def _generate_nx_list(node_type):
    global g
    node_list = []
    for node in g.nodes(data=True):
        if node[1]['node_type'] == node_type:
            # Append a tuple containing the node's ID and the name attribute
            node_list.append((node[0], node[1]['name']))
    return node_list

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
            edge_list.append((edge_attrs[0]['ports'][sw_nx_id], peer_nx_id)) # A tuple containing the port on the switch where peer_nx_id can be found
        peer_list[sw_nx_id] = edge_list
    return peer_list

# We need this because setting the port1/port2 attrs is super unreliable in networkx
# Creating a custom attr named "ports" for each edge allows us to guarantee that the port number will be properly associated with the NX ID of the node
def _generate_port_dict(peer1, peer2, port1, port2):
    return {peer1: port1, peer2: port2}

def _get_node_by_nx_id(node_id):
    global g
    return [node for node in g.nodes(data=True) if node[0] == node_id]
  
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

##############################################
#                  LAUNCH                    #
##############################################

def launch():
    global g, MODULE_START
    MODULE_START = time.time() * 1000
    g = nx.MultiDiGraph()
    
    def start():
        core.openflow.addListenerByName("ConnectionUp", _handle_connectionup)
        core.openflow_discovery.addListenerByName("LinkEvent", _handle_linkevent)
        core.openflow.addListenerByName("PacketIn", _handle_packetin)
        core.register("nxgraph", g)
    core.call_when_ready(start, ('openflow', 'openflow_discovery'))
    # Timer kicks off only once everything else has started - neat!
    # By then, all the switches should be active and have all their edges set in the NX graph object
    Timer(5, _timer_func, recurring=True)
    
# TODO:
# Find a way to do delay calculations between switch-switch links
# Error handling for situations where the mininet instance isn't active (maybe?)
# Add handling for when a host-switch link goes down, removing it from the graph
