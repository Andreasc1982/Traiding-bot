#!/bin/bash
# Adds Port 2222 to sshd, opens ufw, restarts SSH
python3 -c "
content = open('/etc/ssh/sshd_config').read()
if 'Port 2222' not in content:
    open('/etc/ssh/sshd_config','a').write('\nPort 2222\n')
"
ufw allow 2222/tcp
systemctl restart ssh
echo "Done. SSH now on port 22 and 2222."
