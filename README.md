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

[bc]: https://www.scootersoftware.com/
    "Scooter Software: Home of Beyond Compare"
