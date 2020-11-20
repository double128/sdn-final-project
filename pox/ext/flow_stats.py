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

def _handle_connectionup(event):
    global g
    # Add a node to the networkx graph and assign it an identifiable name
    sw_name = "sw" + str(event.dpid)
    g.add_node(event.dpid, name=sw_name)
    

def _timer_func ():
    global g

    # d1 = dpid1; d2 = dpid2; d = attrs as a dict
    #for d1, d2, k, d in graph.edges(data=True, keys=True):
    #    conn1 = core.openflow.connections.get(d1)
    #    conn2 = core.openflow.connections.get(d2)
    #    print(conn1)
    #    print(conn2)


    for connection in core.openflow._connections.values():
        connection.send(of.ofp_stats_request(body=of.ofp_flow_stats_request()))
        connection.send(of.ofp_stats_request(body=of.ofp_port_stats_request()))
    log.debug("Sent %i flow/port stats request(s)", len(core.openflow._connections))

# handler to display flow statistics received in JSON format
# structure of event.stats is defined by ofp_flow_stats()
def _handle_flowstats_received (event):
  stats = flow_stats_to_list(event.stats)
  log.debug("FlowStatsReceived from %s: %s", 
    dpidToStr(event.connection.dpid), stats)
  """
  # Get number of bytes/packets in flows for web traffic only
  web_bytes = 0
  web_flows = 0
  web_packet = 0
  for f in event.stats:
    print(f.duration_sec)
    #if f.match.tp_dst == 80 or f.match.tp_src == 80:
    web_bytes += f.byte_count
    web_packet += f.packet_count
    web_flows += 1
  log.info("Traffic from %s: %s bytes (%s packets) over %s flows", 
    dpidToStr(event.connection.dpid), web_bytes, web_packet, web_flows)
  """

# Portstats handler can be used to calculate bandwith
def _handle_portstats_received(event):
  stats = flow_stats_to_list(event.stats)
  log.debug("PortStatsReceived from %s: %s", 
    dpidToStr(event.connection.dpid), stats)

def _handle_linkevent(event):
    l = event.link
    if event.added:
        _add_graph_edge(l.dpid1, l.dpid2, l.port1, l.port2, "switch") 
    elif event.removed:
        _set_graph_edge_state(l.dpid1, l.dpid2, state=False)

def _add_graph_edge(peer1, peer2, port1, port2, link_type):
    global g
    if link_type == "switch":
        _gen_link_state_log(peer1, peer2, "Adding new switch-switch edge to graph")
        # Edges are initialized with zero values for usage and delay, they'll be computed later
        # state=True means the link is up
        g.add_edge(peer1, peer2, port1=port1, port2=port2, usage=0, delay=0, state=True)
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

def _find_graph_node(attr, val):
    global g 
    return any([node for node in g.nodes(data=True) if node[1][attr] == val])

def _handle_packetin(event):
    global g
    sw_dpid = event.dpid
    in_port = event.port
    packet = event.parsed
    
    host_src_mac = str(packet.src)
    host_id = host_src_mac[-1]      # This should not be passed into networkx, this is JUST for getting the name of the node (which corresponds to MAC address)
    host_name = "h" + str(host_id)

    # If our host isn't in our graph object, we need to add it
    if not _find_graph_node("name", host_name):
        # Since we need to provide an ID for each node, we can just increment the number of nodes by 1 to get a unique ID
        host_node_id = g.number_of_nodes() + 1
        g.add_node(host_node_id, name=host_name)
        
    _dump_graph_json_data()

    #if not g.has_node(host_name):


    

    
    #in_port = event.ofp.in_port
    #if in_port 
    #rt
    #print(vars(g))
    #msg = of.ofp_packet_out(data=event.ofp)
    #print(msg)

def _gen_link_state_log(dpid1, dpid2, msg):
    log.info(str(dpid1) + " -> " + str(dpid2) + ": " + msg)

#def _get_link_delay():

def _dump_graph_json_data():
    global g
    print(json.dumps(json_graph.node_link_data(g),indent=2))
    

def launch():
    global g
    g = nx.MultiDiGraph()
    
    core.openflow.addListenerByName("ConnectionUp", _handle_connectionup)
    core.openflow.addListenerByName("FlowStatsReceived", _handle_flowstats_received) 
    core.openflow.addListenerByName("PortStatsReceived", _handle_portstats_received) 
    core.openflow_discovery.addListenerByName("LinkEvent", _handle_linkevent)
    core.openflow.addListenerByName("PacketIn", _handle_packetin)


    Timer(5, _timer_func, recurring=True)

# TODO:
# Add a broadcast flow rule on ConnectionUp for each switch that matches any Ethernet traffic to 255.255.255.255 with action flood
