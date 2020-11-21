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
                #spath = nx.shortest_path(g, source=h[0], target=o[0])
                spath = nx.dijkstra_path(g, source=h[0], target=o[0])
                print("#### BEST PATH FOR " + str(h[1]) + " -> " + str(o[1]))
                print(spath)
                _generate_flow_rules(spath)

   # for 
    #short_path = g.shortest_path(
    #for connection in core.openflow._connections.values():
        #connection.send(of.ofp_stats_request(body=of.ofp_flow_stats_request()))
        #connection.send(of.ofp_stats_request(body=of.ofp_port_stats_request()))
    #log.debug("Sent %i flow/port stats request(s)", len(core.openflow._connections))

def _handle_linkevent(event):
    l = event.link
    dpid1 = dpidToStr(l.dpid1)
    dpid2 = dpidToStr(l.dpid2)

    if event.added:
        _add_graph_edge(dpid1, dpid2, l.port1, l.port2, "switch") 

    elif event.removed:
        #_set_graph_edge_state(dpid1, dpid2, state=False)
        pass
        # NOTE: For now, do nothing. We might not need to handle this

def _add_graph_edge(peer1, peer2, port1, port2, link_type):
    global g
    if link_type == "switch":
        _gen_link_state_log(peer1, peer2, "Adding new switch-switch edge to graph")
        # Edges are initialized with zero values for usage and delay, they'll be computed later
        # state=True means the link is up
        # All switch-switch edges are initialized with a weight of 1.0. This weight value is adjusted as bandwidth and delay calculations run
        # NOTE: I'm removing the "state" arg because I don't think we'll need it
        g.add_edge(peer1, peer2, port1=port1, port2=port2, weight=1.0, link_type="switch")
    elif link_type == "host":
        # PEER1 MUST BE THE HOST DO NOT MESS THIS UP
        _gen_link_state_log(peer1, peer2, "Adding new host-switch edge to graph")
        g.add_edge(peer1, peer2, port1=port1, port2=port2, link_type="host")

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
    #print(msg)
    self.connection.send(msg)

def _generate_flow_rules(path):
    """
    Inputs:
    path - a list of nodes representing the path selected between two hosts
        for example, ['00:00:00:00:00:02', '00-00-00-00-00-01', '00-00-00-00-00-04', '00:00:00:00:00:07']

    Function will dynamically create rules to enable each hop in the given path and install those rules on all switches in path

    Returns: N/A
    """
    path = ['00:00:00:00:00:02', '00-00-00-00-00-01', '00-00-00-00-00-04', '00:00:00:00:00:07']
    
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
    path = path[1:-1]
    #for each hop in the path...
    for source, dest in zip(path, path[1:]):
        edge = g.edges.get((source,dest)) #get the edge between the two switches
        if edge:
            output_port = edge.get('port1') if edge.get('target') == dest else edge.get('port2')

            msg = of.ofp_flow_mod()
            msg.match.dl_src = EthAddr(source_mac)
            msg.match.dl_dst = EthAddr(dest_mac)
            msg.hard_timeout = 30
            msg.idle_timeout = 10
            msg.actions = [of.ofp_action_output(port=output_port)]
            if g.nodes.get(source):
                g.nodes.get(source).get('connection').send(msg)
            else:
                log.error("Failed to install flow for "+source_mac+"->"+dest_mac+" on "+source)



def _handle_packetin(event):
    global g
    packet = event.parsed
    
    #if packet.type == packet.LLDP_TYPE or packet.dst.isBridgeFiltered():
    #    _drop_packet_handler(packet)
    
    host_mac = str(packet.src)
    host_name = "h" + str(host_mac[-1])
    
    # If we don't get a result back for this, this means there's no node for this host yet
    if not _get_node_obj_by_name(host_name):
        g.add_node(host_mac, name=host_name, node_type="host")

    sw_port = event.port
    sw_dpid = dpidToStr(event.dpid)
    
    # Host nodes should only have an edge added if they don't have any edges. Hosts can only have 1 edge, which will be the link to their switch
    if len(g.edges([host_mac])) == 0:
        # Check if the edge exists already, if it doesn't, create it
        if not g.has_edge(host_mac, sw_dpid):
            # "0" is the host's port; this will always be 0
            # Also, make sure host_mac is the first arg, the _add_graph_edge method needs it like that
            # TODO: Add handling for that. You honestly don't need to. You REALLY don't need to. But god, you WANT to.
            _add_graph_edge(host_mac, sw_dpid, 0, sw_port, "host")
        
    #_dump_graph_json_data()

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
    _save_graph_json_data()
    log.info(str(peer1) + " -> " + str(peer2) + ": " + msg)

#def _get_link_delay():

def _dump_graph_json_data():
    global g
    print(json.dumps(json_graph.node_link_data(g),indent=2,default=lambda o: '<not serializable>'))

def _save_graph_json_data():
    global g
    f = open("networkx_graph.json",'w')
    f.write(json.dumps(json_graph.node_link_data(g),indent=2,default=lambda o: '<not serializable>'))
    f.close()

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
