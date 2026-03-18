from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.lib.packet import ether_types
from ryu.lib.packet import in_proto
from ryu.lib.packet import ipv4
from ryu.lib.packet import icmp
from ryu.lib.packet import tcp
from ryu.lib.packet import udp
from ryu.lib.packet import arp

from ryu.topology import event, switches
from ryu.topology.api import get_switch, get_link, get_host
from ryu.lib import hub
import networkx as nx
from ryu import cfg

from time import sleep
import time

NUM_OF_PKTS = 2                    ###packet for latency monitoring- higher better accracy but overhead
INTERVAL = 10                      ### latency measuring interval
DISCOVERY_INERVAL = 30             ### interval for topology discovery


TOPOLOGY_DISCOVERED = 0
keystore = {}




class MPathLatency(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(MPathLatency, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.topology_api_app = self
        self.topodiscovery_thread = hub.spawn(self._tdiscovery)    
        self.datapaths = {}
        self.latency_db = {} 
        self.switches = None
        self.links = None
        self.hosts = None
        self.controller_ip = "1.1.1.1"                      ###generatig ping packet from Co to switch for latency stats
        self.controller_mac = "11:11:11:11:11:11" 
        self.link_thread = hub.spawn(self._linkstats)       ###refr 59

    def _tdiscovery(self):
        global TOPOLOGY_DISCOVERED
        hub.sleep(DISCOVERY_INERVAL)
        self.get_topology_data()                   ###function in line 120
        TOPOLOGY_DISCOVERED = 1

    def _linkstats(self):
        hub.sleep(DISCOVERY_INERVAL)
        while(1):
            hub.sleep(INTERVAL)
            self.monitor_link_latency()            ###function in line 67
            hub.sleep(1)
            self.calculate_pktlatency()            ###function in line 102

    def monitor_link_latency(self):
        self.logger.info("Monitoring Link Latency....")
        for seqno in range(1, NUM_OF_PKTS+1):
            #self.logger.info("Latency measurements - seq no %d ",  seqno)
            for datapath in self.datapaths:
                self.send_ping_packet(self.datapaths[datapath], seqno)         ###function in line 75
                sleep(0.01)

    def send_ping_packet(self, datapath, seqno):
        ofp = datapath.ofproto
        parser = datapath.ofproto_parser
        dpid = datapath.id
        actions = [parser.OFPActionOutput(ofp.OFPP_FLOOD)]
        pkt = packet.Packet()                                                    ###construc ping packet
        pkt.add_protocol(ethernet.ethernet(ethertype=ether_types.ETH_TYPE_IP,
                                            src=self.controller_mac,
                                            dst=self.controller_mac))
        pkt.add_protocol(ipv4.ipv4(proto=in_proto.IPPROTO_ICMP,
                                    src=self.controller_ip,
                                    dst=self.controller_ip))
        echo_payload = '%d;%d;%f' % (dpid, seqno, time.time())
        #payload = icmp.echo(data=echo_payload)
        payload = icmp.echo(data=echo_payload.encode('utf-8'))
        pkt.add_protocol(icmp.icmp(data=payload))
        pkt.serialize()

        out = datapath.ofproto_parser.OFPPacketOut(                              ###sent out the ping packet
                datapath=datapath,
                buffer_id=datapath.ofproto.OFP_NO_BUFFER,
                data=pkt.data,
                in_port=datapath.ofproto.OFPP_CONTROLLER,                
                actions=actions
            )
        datapath.send_msg(out)

    def calculate_pktlatency(self):        ###calculate avg latency for src to dest and updaate db
        for sender in self.latency_db:
            for receiver in self.latency_db[sender]:
                no_of_samples = len(self.latency_db[sender][receiver]["latency"])
                total_latency = sum(self.latency_db[sender][receiver]["latency"])

                if no_of_samples >= 1:
                    self.latency_db[sender][receiver]["avg_latency"] =  total_latency / no_of_samples
                else:
                    self.latency_db[sender][receiver]["avg_latency"] = 0

        for sender in self.latency_db:
            for receiver in self.latency_db[sender]:
                #rese
                self.latency_db[sender][receiver]["latency"] = []
                self.latency_db[sender][receiver]["seqno"] = []


    def get_topology_data(self):                            #####print out the "toplogy discoverd" and all related info
        switch_list = get_switch(self.topology_api_app, None)
        switches = [switch.dp.id for switch in switch_list]
        links_list = get_link(self.topology_api_app, None)
        links = [(link.src.dpid, link.dst.dpid, {'port': link.src.port_no, 'weight': 1}) for link in links_list]
        host_list = get_host(self.topology_api_app, None)
        hosts = [(host.mac, host.port.dpid, {'port': host.port.port_no}) for host in host_list]
        self.switches = switches
        self.links = links
        self.hosts = hosts
        self.logger.info("Topology discovered")
        self.logger.info("switches %s Links %s  Hosts %s ", switches, links, hosts)
        self.build_topology()

    def build_topology(self):              ###using netx by feeding all daata collectedt in 120 to built logical network espression
        #print 'Building  the topology'
        self.networkx = None
        self.networkx = nx.Graph()
        for s in self.switches:
            self.networkx.add_node(s, name=s)
        for l in self.links:
            self.networkx.add_edge(l[0], l[1], weight=1)  
            self.latency_db[l[0]].setdefault(l[1], {})
            self.latency_db[l[0]][l[1]].setdefault("seqno", [])
            self.latency_db[l[0]][l[1]].setdefault("latency", [])
            self.latency_db[l[0]][l[1]].setdefault("avg_latency", 0)

    def shortest_path(self, snode, dnode):              ####not used
        spath = nx.dijkstra_path(self.networkx, snode, dnode)
        print(spath)
        return spath

    def all_paths(self, snode, dnode):                    ###display "shortest path calculation A to B, all path XXXX"
        paths = list(nx.all_simple_paths(self.networkx, snode, dnode))
        return paths

    def get_dpid(self,mac):
        '''                
        #('00:00:00:00:00:01', 10, {'port': 4})
        '''        
        for host in self.hosts:
            if host[0] == mac:
                return host

    def get_portnumber(self,srcdpid,dstdpid):
        for link in self.links:
            if link[0]==srcdpid and link[1]==dstdpid:
                return link[2]["port"]

    def create_path(self, dpid, smac, dmac, outport,srcip,dstip, protocol, srcport, dstport):
        datapath = self.datapaths[dpid]
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        if protocol == in_proto.IPPROTO_ICMP:
            match = parser.OFPMatch(eth_dst=dmac, eth_src=smac,eth_type=ether_types.ETH_TYPE_IP,
                                ipv4_src=srcip, ipv4_dst=dstip, ip_proto=protocol)
        elif protocol == in_proto.IPPROTO_TCP:
            match = parser.OFPMatch(eth_dst=dmac, eth_src=smac,eth_type=ether_types.ETH_TYPE_IP,
                                ipv4_src=srcip, ipv4_dst=dstip, ip_proto=protocol, tcp_src=srcport, tcp_dst=dstport,)
        elif protocol == in_proto.IPPROTO_UDP:
            match = parser.OFPMatch(eth_dst=dmac, eth_src=smac,eth_type=ether_types.ETH_TYPE_IP,
                                ipv4_src=srcip, ipv4_dst=dstip, ip_proto=protocol, udp_src=srcport, udp_dst=dstport,)

        actions = [parser.OFPActionOutput(outport)]
        self.add_flow(datapath, 10, match, actions)



    def get_path_latency(self, path):
        total_pathloss = 0
        total_latency = 0

        length =len(path)
        for i in range(0,length-1):
            sender = path[i]
            receiver = path[i+1]
            avg_latency = self.latency_db[sender][receiver]["avg_latency"]
            #self.logger.info("src %s ds %s  avg latency %s", sender, receiver, avg_latency)
            total_latency = total_latency + avg_latency
        self.logger.info("path  %s , total_latency %s ", path, total_latency)
        return total_latency


    def find_shortest_latency_path(self,dpid, srcmac, dstmac, srcip, dstip, protocol, srcport, dstport):
        self.logger.info("Shortest path calcaulation %s to %s" , srcmac , dstmac)
        # Get the Switch connected to Source Host
        result = self.get_dpid(srcmac)
        srcdpid = result[1]
        # Get the Switch connected to Destination Host
        result = self.get_dpid(dstmac)
        dstdpid = result[1]
        dst_port = result[2]

        #check whether both srchost and dsthost connected on same switch then return the port
        if srcdpid == dstdpid:
            self.create_path(srcdpid, srcmac, dstmac, dst_port['port'], srcip, dstip, protocol, srcport, dstport)
            return dst_port['port']
        # get the shortest path between the swicthes(srchost connected & destination host connected)
        pathss = self.all_paths(srcdpid, dstdpid)
        self.logger.info("all paths %s", pathss)

        lowsest_path = []
        lowsest_loss = None
        lowsest_latency = None
        #choose lowsest loss the pathe 
        for paths in pathss:
            pathlatency = self.get_path_latency(paths)
            if lowsest_latency == None:
                lowsest_latency =  pathlatency
                lowsest_path = paths
                continue
            if pathlatency < lowsest_latency:
                lowsest_latency =  pathlatency
                lowsest_path = paths

        paths = lowsest_path
        self.logger.info( " Selected Path is %s", paths)
        #get port number for each path:
        index = 0
        length = len(paths)
        for x in range(0, length-1):
            srcdpid = paths[x]
            nexthop = paths[x+1]
            #self.logger.info('Finding port src %d dst %d ', srcdpid, nexthop)
            port = self.get_portnumber(srcdpid, nexthop)
            #self.logger.info("port %d", port)
            path = {"dpid": srcdpid, "src_mac":srcmac, "dst_mac": dstmac, "port": port}
            self.create_path(srcdpid, srcmac, dstmac, port, srcip, dstip, protocol, srcport, dstport)

        # Add a flow in the switch which is connected to the destination host             
        # As this is destination switch, this can be added last(otherwise timing issue of original packetout)
        self.create_path(dstdpid, srcmac, dstmac, dst_port['port'], srcip, dstip, protocol, srcport, dstport)
        # packet need to send out, hence we need return the immediate next path
        srcdpid = paths[0]
        nexthop = paths[1]      
        port = self.get_portnumber(srcdpid, nexthop)
        #small wait time for installing  all the paths(because its openflow msgs - async).
        sleep(0.05)    ####may need to increase if topology gets big, pc slow
        return port

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        self.datapaths[datapath.id] = datapath
        # install table-miss flow entry
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions,idle_t=0, hard_t=0)

        # installing  the flow for controller ping packets
        match = parser.OFPMatch(eth_dst=self.controller_mac, eth_src=self.controller_mac,eth_type=ether_types.ETH_TYPE_IP,
                                ipv4_src=self.controller_ip, ipv4_dst=self.controller_ip)

        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 100, match, actions,idle_t=0, hard_t=0)        

        self.latency_db.setdefault(datapath.id, {})
        #print "ladb switch_features_handler", self.latency_db

    def add_flow(self, datapath, priority, match, actions, buffer_id=None, idle_t=30, hard_t=0):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,
                                             actions)]
        if buffer_id:
            mod = parser.OFPFlowMod(datapath=datapath, buffer_id=buffer_id,
                                    priority=priority, idle_timeout=idle_t, hard_timeout=hard_t,
                                    match=match, instructions=inst)
        else:
            mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                    idle_timeout=idle_t, hard_timeout=hard_t,
                                    match=match, instructions=inst)
        datapath.send_msg(mod)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        if ev.msg.msg_len < ev.msg.total_len:
            self.logger.debug("packet truncated: only %s of %s bytes",
                              ev.msg.msg_len, ev.msg.total_len)
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            # ignore lldp packet
            return
        dst = eth.dst
        src = eth.src

        dpid = datapath.id
        self.mac_to_port.setdefault(dpid, {})
        #self.logger.info("packet in %s src %s dst %s in_port %s type %s", dpid, src, dst, in_port,eth.ethertype)

        #Do not process any packet before topology discovery
        if not TOPOLOGY_DISCOVERED:
            #self.logger.info("Dropping the packet...Topology discovery inprogress")
            return

        #DROP BROADCAST and IPv6 MULICAST Packe
        if dst == "ff:ff:ff:ff:ff:ff" or dst[:5] == "33:33" or dst[0:1] == "33:33":
            #self.logger.info("drop broadcast/ipv6 multicast packet %s", dst)
            return

        # check IP Protocol and create a match for IP
        if eth.ethertype == ether_types.ETH_TYPE_IP:
            ip = pkt.get_protocol(ipv4.ipv4)
            srcip = ip.src
            dstip = ip.dst
            protocol = ip.proto

            if srcip == self.controller_ip and dstip == self.controller_ip:    ##function when receiving ping packet for latency
                icmp_packet = pkt.get_protocol(icmp.icmp)
                echo_payload = icmp_packet.data
                #payload = echo_payload.data
                payload = echo_payload.data.decode('utf-8')
                info = payload.split(';')
                sender = info[0]
                seqno = info[1]
                sender_time = info[2]
                receiver_time = time.time()
                latency = (receiver_time - float(sender_time)) * 1000 # in ms
                receiver = dpid
                #print "sender %s seqno %s sender time %s receiver %s  receiver time %s latency %d" % (sender, seqno, sender_time, receiver, receiver_time, latency)
                #self.process_latency(sender, receiver, seqno, latency, sender_time, receiver_time )
                self.latency_db[int(sender)][int(receiver)]["seqno"].append(seqno)
                self.latency_db[int(sender)][int(receiver)]["latency"].append(latency)
                return

            if protocol == in_proto.IPPROTO_TCP:
                t = pkt.get_protocol(tcp.tcp)
                srcport = t.src_port
                dstport = t.dst_port
            elif protocol == in_proto.IPPROTO_UDP:
                u = pkt.get_protocol(udp.udp)
                srcport = u.src_port
                dstport = u.dst_port
            else:
                srcport = 0
                dstport = 0

            oport = self.find_shortest_latency_path(dpid, src, dst, srcip, dstip, protocol, srcport, dstport)
            if oport:
                actions = []
                actions.append(parser.OFPActionOutput(oport))
                out = parser.OFPPacketOut(datapath=datapath, buffer_id=ofproto.OFP_NO_BUFFER,
                                        in_port=in_port, actions=actions, data=msg.data)
                datapath.send_msg(out)            
