# SDN Final Project

### Installation
```
$ sudo apt install mininet
$ git clone git://github.com/mininet/mininet
$ mininet/util/install.sh -fw
$ git clone http://github.com/noxrepo/pox
$ pip install libtmux
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


