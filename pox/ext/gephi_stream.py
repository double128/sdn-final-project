from pox.core import core
from pox.lib.util import dpid_to_str
from pox.lib.ioworker.workers import *
from pox.lib.ioworker import *
from pox.lib.recoco import Timer

import json

log = core.getLogger()

loop = None

clients = set()

class GephiHTTPWorker (RecocoIOWorker):
    # HTTP worker input states.  It'd be nice to reuse the web component, but
    # it seemed a bit awkward with Gephi's (sort of unusual) streaming.
    class HEADER: pass
    class BODY: pass
    class DEAD: pass

    def __init__ (self, *args, **kw):
        super(GephiHTTPWorker, self).__init__(*args, **kw)
        self._connecting = True
        self.data = b''
        self._state = self.HEADER

    def _handle_close (self):
        log.info("Client disconnect")
        super(GephiHTTPWorker, self)._handle_close()
        clients.discard(self)

    def _handle_connect (self):
        log.info("Client connect")
        super(GephiHTTPWorker, self)._handle_connect()
        clients.add(self)

    def _handle_rx (self):
        self.data += self.read().replace(bytes("\r", "utf-8"), bytes("", "utf-8"))
        while True:
            datalen = len(self.data)

            if self._state is self.HEADER:
                if bytes('\n\n',"utf-8") in self.data:
                    header,self.data = self.data.split(bytes('\n\n', "utf-8"), 1)
                    self._process_header(header)
            elif self._state is self.BODY:
                pass

            if datalen == len(self.data): break

    def _process_header (self, request):
        request = request.strip().split(bytes("\n", "utf-8"))
        if not request: return
        req = request[0]
        #kv = {}
        #for r in request[1:]:
        #  k,v = r.split(':', 1)
        #  kv[k] = v

        if bytes('POST',"utf-8") in req:
            self._state = self.BODY
            self.shutdown()
            return

        # Assume it's a GET /
        self.send_full()

    def send_full (self):
        out = core.GephiStream.get_full()
        self.send_json(out)

    def send_json (self, m):
        # Build the body...
        b = '\r\n'.join(json.dumps(part) for part in m)
        b += '\r\n'

        # Build the header...
        h = []
        h.append('HTTP/1.1 200 OK')
        h.append('Content-Type: test/plain') # This is what Gephi claims
        #h.append('Content-Length: ' + str(len(d)))
        h.append('Server: POX/%s.%s.%s' % core.version)
        h.append('Connection: close')
        h = '\r\n'.join(h)

        self.send(h + '\r\n\r\n' + b)

    def send_msg (self, m):
        self.send_json([m])

def an (n, **kw):
    kw['label'] = str(kw['label']) if kw.get('label') else str(n)
    return {'an':{str(n):kw}}

def ae (a, b, weight=1.0):
    a = str(a)
    b = str(b)
    return {'ae':{a+"_"+b:{'source':a,'target':b,'directed':True,'weight':weight}}}

def de (a, b):
    a = str(a)
    b = str(b)
    return {'de':{a+"_"+b:{}}}

def dn (n):
    return {'dn':{str(n):{}}}

def ce (a, b, weight=1.0):
    a = str(a)
    b = str(b)
    return {'ce':{a+"_"+b:{"weight":weight}}}

def clear ():
    return {'dn':{'filter':'ALL'}}

class GephiStream(object):
    def __init__ (self):
        self.nodes = set()
        self.edges = set()
    
    def send(self,data):
        for c in clients:
            c.send_msg(data)

    def get_full(self):
        out = []

        #out.append(clear())

        for n in self.nodes:
            out.append(an(n))
        for e in self.edges:
            out.append(ae(e[0],e[1]))
        return out

    def run(self):
        for node in core.nxgraph.nodes(data=True):
            self.send(an(node[0], label=node[1].get('name')))
        for edge in core.nxgraph.edges(data=True):
            log.info(edge)
            self.send(ae(edge[0],edge[1],edge[2].get('weight',1.0)))
            self.send(ce(edge[0],edge[1],edge[2].get('weight',1.0)))



def launch (port = 8282, __INSTANCE__ = None):
    if not core.hasComponent("GephiStream"):
        core.registerNew(GephiStream)

    global loop
    if not loop:
        loop = RecocoIOLoop()
        #loop.more_debugging = True
        loop.start()

    Timer(5, GephiStream().run, recurring=True)

    worker_type = GephiHTTPWorker
    w = RecocoServerWorker(child_worker_type=worker_type, port = int(port))
    loop.register_worker(w)