nv set system hostname tor5

# Configure bond1 as a LAG with swp1 and swp2 as members
nv set interface bond1 bond member swp1
nv set interface bond1 bond member swp2

# Set the LAG mode to LACP
nv set interface bond1 bond mode lacp

# Put the LAG into the default VLAN-aware bridge
nv set interface bond1 bridge domain br_default

# Allow VLAN 10 in the bridge
nv set bridge domain br_default vlan 10

# Restrict the LAG to VLAN 10 only
nv set interface bond1 bridge domain br_default vlan 10

# Make it pure tagged interface; drop untagged
nv set interface bond1 bridge domain br_default untagged none

# Add swp3 and swp4 to the bridge as untagged/access VLAN 10
nv set interface swp3 bridge domain br_default
nv set interface swp3 bridge domain br_default access 10
nv set interface swp4 bridge domain br_default
nv set interface swp4 bridge domain br_default access 10

# Enable PortFast and BPDU guard on server facing ports
nv set interface swp3 bridge domain br_default stp admin-edge enable
nv set interface swp3 bridge domain br_default stp bpdu-guard enable
nv set interface swp4 bridge domain br_default stp admin-edge enable
nv set interface swp4 bridge domain br_default stp bpdu-guard enable

nv config apply
