# beyond-ssh

Has this ever happened to you?

You are SSHed into a remote machine, you do a `git merge`, and suddenly there's
a merge conflict. Unfortunately, your [favourite merge tool][bc] is not installed
on the remote machine, so you must perform the merge by hand.

No more!

With beyond-ssh you can use your local installation of Beyond Compare as a difftool
and mergetool on remote machines.

## Usage

### Remote

Add this to your `.gitconfig`:

```gitconfig
[diff]
    tool = beyond-ssh
[difftool "beyond-ssh"]
    cmd = /path/to/beyond_ssh.py diff $LOCAL $REMOTE
    trustExitCode = true
[merge]
    tool = beyond-ssh
[mergetool "beyond-ssh"]
    cmd = /path/to/beyond_ssh.py merge $LOCAL $REMOTE $BASE $MERGED
    trustExitCode = true
```

Now, when running `git difftool` or `git mergetool` you will see:

```plain
beyond-ssh:INFO:Listening on port XXXXX
```

Which indicates that the tool is waiting for a connection from you local machine
on the specified port.

### Local

Once the server is running on the remote machine, run this on your local machine:

```bash
./beyond_ssh.py connect <remote address> <remote port>
```

This will launch Beyond Compare in the correct mode (diff or merge), wait for it
to exit, and communicate the return code to the server. The server will then return
this code to Git.

If the remote machine blocks connections on arbitrary ports, try passing `-t`
to tunnel over SSH.

Pass `-h / --help` to the script for extended usage information.

### Automation

When beyond-ssh is running in server mode it accepts an additional parameter &mdash;
`-f`. This allows you to specify a custom format string that will be used
when displaying the port the server is listening on.

The format string accepts the following substitutions:

- `{e}` - Expands to the ESC character (`0x1B`).
- `{b}` - Expands to the BEL character (`0x07`).
- `{port}` - Expands to the port number.
- `{port_b64}` - Expands to the port number, encoded in Base64.

This is useful because now we can emit a custom ANSI escape sequence
when the server is launched. This sequence can then be interpreted by your terminal
application to automatically launch the beyond-ssh client!

For instance, if you're using [WezTerm][wez] you can use the following `.gitconfig`:

```gitconfig
[diff]
    tool = beyond-ssh
[difftool "beyond-ssh"]
    cmd = "/path/to/beyond_ssh.py diff -f \"Listening on port {port}{e}]1337;SetUserVar=BeyondSSHPort={port_b64}{b}\" $LOCAL $REMOTE"
    trustExitCode = true
[merge]
    tool = beyond-ssh
[mergetool "beyond-ssh"]
    cmd = "/path/to/beyond_ssh.py merge -f \"Listening on port {port}{e}]1337;SetUserVar=BeyondSSHPort={port_b64}{b}\" $LOCAL $REMOTE $BASE $MERGED"
    trustExitCode = true
```

Which will set the `BeyondSSHPort` user var whenever the server is launched.
You can then use the `user-var-changed` event to launch beyond-ssh.

If you're using tmux the escape sequence has to be wrapped:

```gitconfig
[diff]
    tool = beyond-ssh
[difftool "beyond-ssh"]
    cmd = "/path/to/beyond_ssh.py diff -f \"Listening on port {port}{e}Ptmux;{e}{e}]1337;SetUserVar=BeyondSSHPort={port_b64}{b}{e}\\\\\" $LOCAL $REMOTE"
    trustExitCode = true
[merge]
    tool = beyond-ssh
[mergetool "beyond-ssh"]
    cmd = "/path/to/beyond_ssh.py merge -f \"Listening on port {port}{e}Ptmux;{e}{e}]1337;SetUserVar=BeyondSSHPort={port_b64}{b}{e}\\\\\" $LOCAL $REMOTE $BASE $MERGED"
    trustExitCode = true
```

[bc]: https://www.scootersoftware.com/
    "Scooter Software: Home of Beyond Compare"

[wez]: https://wezfurlong.org/wezterm/index.html
    "wezterm - Wez's Terminal Emulator"
