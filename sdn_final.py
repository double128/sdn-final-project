import os
import time
import libtmux

class SDNFinal:
    def __init__(self):
        self.session_name = "sdn_final"
        # We should be keeping track of the root directory (in this case, the project directory) to ensure the tmux panes know where to find their files
        self.root_dir = os.path.dirname(os.path.abspath(__file__))
        tmux_sess = self.setup_tmux_session()
        tmux_sess.attach_session()

    def setup_tmux_session(self):
        server = libtmux.Server()
        try:
            session = server.find_where({"session_name": self.session_name})
            print("\033[93m\n\n[!] It looks like there's already an active tmux session.")
            # Since we are using Python2.7, we need to use raw_input() instead of input()
            res = raw_input("Do you want to destroy the existing one and create a new one? [Y/N]:\033[0m ")
            if res.lower() == "y":
                window = session.windows[0]
                # We need to gracefully shut down the mininet and Pox instances
                # We know that the mininet pane will always be 0 so setting a variable seems kinda useless and a waste of effort
                window.panes[0].send_keys('exit')
                # We need to pass in "suppress_history" as explained here => https://github.com/tmux-python/libtmux/issues/88#issuecomment-354008962
                window.panes[1].send_keys('C-c', suppress_history=False)
                time.sleep(1)
                server.kill_session(self.session_name)
                # This is very hacky - once we kill the existing session, just raise the same error we'd get if "server.find_where" returned nothing
                raise libtmux.exc.LibTmuxException
        except libtmux.exc.LibTmuxException:
            session = server.new_session(session_name=self.session_name, start_directory=self.root_dir)
            window = session.windows[0]
            # vertical=False will split the panes in a way where they're displayed side by side
            window.split_window(vertical=False)
            mn_pane = window.panes[0]
            pox_pane = window.panes[1]
            
            print(" \033[96m-> Cleaning up mininet junk...\033[0m")
            os.system('mn -c')
            
            print(" \033[96m-> Initializing Pox controller...\033[0m")
            pox_pane.send_keys("cd pox")
            #pox_pane.send_keys("./pox.py samples.pretty_log openflow.discovery forwarding.l2_learning openflow.spanning_tree --no-flood --hold-down misc.gephi_topo flow_stats")
            pox_pane.send_keys("./pox.py samples.pretty_log openflow.discovery openflow.spanning_tree --no-flood --hold-down flow_stats")
            # Sleep for a few seconds so Pox can set itself up before we initialize mininet
            time.sleep(2)

            print(" \033[96m-> Initializing mininet network...\033[0m")
            mn_pane.send_keys("sudo python topology_setup.py")
        return session
        #import code; code.interact(local=dict(globals(), **locals()))

if __name__ == '__main__':
    SDNFinal()
