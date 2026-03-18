#!/usr/bin/python


from mininet.topo import Topo
from mininet.net import Mininet
from mininet.log import setLogLevel
from mininet.cli import CLI
from mininet.link import TCLink
from mininet.node import RemoteController,OVSKernelSwitch
from time import sleep


class Multipahtopo(Topo):
    "Single switch connected to n hosts."

    def build(self):
        s1 = self.addSwitch('s1', cls=OVSKernelSwitch)
        s2 = self.addSwitch('s2', cls=OVSKernelSwitch)
        s3 = self.addSwitch('s3', cls=OVSKernelSwitch)
        s4 = self.addSwitch('s4', cls=OVSKernelSwitch)
        s5 = self.addSwitch('s5', cls=OVSKernelSwitch)
        s6 = self.addSwitch('s6', cls=OVSKernelSwitch)


        h1 = self.addHost('h1', mac="00:00:00:00:00:01", ip="192.168.1.1/24")
        h2 = self.addHost('h2', mac="00:00:00:00:00:02", ip="192.168.1.2/24")
        h3 = self.addHost('h3', mac="00:00:00:00:00:03", ip="192.168.1.3/24")
        h4 = self.addHost('h4', mac="00:00:00:00:00:04", ip="192.168.1.4/24")

        self.addLink(s1, s2, 1, 1, cls=TCLink, bw=10, delay='10ms' )
        self.addLink(s1, s3, 2, 1 , cls=TCLink, bw=10, delay='5ms' )
        self.addLink(s1, s5, 3, 1, cls=TCLink, bw=10, delay='100ms' )


        self.addLink(s2, s6, 2, 1, cls=TCLink, bw=10, delay='10ms' )

        self.addLink(s3, s4, 2, 1, cls=TCLink, bw=10, delay='5ms')#, cls=TCLink, bw=1)
        self.addLink(s4, s6, 2, 2, cls=TCLink, bw=10, delay='1ms')#, cls=TCLink, bw=1)

        self.addLink(s5, s6, 2, 3, cls=TCLink, bw=10, delay='1ms')#, cls=TCLink, bw=1)



        self.addLink(h1, s1, 1, 4)
        self.addLink(h2, s1, 1, 5)
        self.addLink(h3, s6, 1, 4)
        self.addLink(h4, s6, 1, 5)


if __name__ == '__main__':
    setLogLevel('info')
    topo = Multipahtopo()
    c1 = RemoteController('c1', ip='127.0.0.1')
    net = Mininet(topo=topo, controller=c1)
    net.start()
    net.staticArp()
    sleep(1)
    # get the host objects
    print("Generating sample ping packets")
    h1 = net.get('h1')
    h2 = net.get('h2')
    h3 = net.get('h3')
    h4 = net.get('h4')
    h1.cmd('ping -c3 192.168.1.2 -W 1')
    h2.cmd('ping -c3 192.168.1.3 -W 1')
    h3.cmd('ping -c3 192.168.1.4 -W 1')
    h4.cmd('ping -c3 192.168.1.1 -W 1')
    #sleep(1)
    #net.pingAll()
    #net.pingAll()
    CLI(net)
    net.stop()
