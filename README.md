# SDN Final Project

### Installation
```
$ sudo apt install mininet
$ git clone git://github.com/mininet/mininet
$ mininet/util/install.sh -fw
$ pip install libtmux
$ pip install pyyaml
$ pip3 install networkx 	# DO NOT TYPE "pip" HERE, YOU NEED "pip3"
```

Should this be in a virtual environment? Yes. Will this project be moved into a virtual environment? Maybe someday.

### Initializing 
Run the following command to get everything up and running:

```
$ ./run.sh
```

### Take NOTE
* Since mininet has to run as root, we will also force `libtmux` to run as root. This means that if you run `tmux ls` after having started the script, you won't see anything there.
	* This is because all tmux sessions will be hosted on `root`'s socket (/tmp/tmux-0/default), and not `$(whoami)`'s (/tmp/tmux-$UID/default). If you run `sudo su` and then `tmux ls`, you should see the session there.
* You can leave the tmux session by hitting CTRL+B, then CTRL+D. This will detach you from the tmux session, but leave it running in the background. 
* A YML file is used to set up all the links in the network. The format is:
```
<switch>: 
	<peer>: <port on "switch" that connects to "peer">
```
* Pox requires Python3. Mininet requires Python2.7. KEEP THIS IN MIND. 
* The Pox directory contains some necessary patches for the `topo_gephi` module to work. Make sure you use this fork of Pox. You will have a hard time if you don't.
