# Collapsed Spine NVD — Topology Diagrams

All values verified against the without-EDA configs
(`collapsed-spine-without-eda/configs/*.cli`).

**Color legend:** green = spine (collapsed spine + border-leaf), purple = ToR
(access-only), blue = Linux host, grey = annotation/metadata.

**The one big idea:** the two spines are an *eBGP underlay* carrying an
*EVPN-VXLAN overlay*. The underlay's only job is to give every spine a reachable
loopback (VTEP). The overlay then builds all L2 and L3 services on top by
exchanging EVPN routes. The four diagrams below follow that exact build order:
**(1) underlay → (2) access/multihoming → (3) services → (4) endpoints.**

## 1 — Underlay / Physical Fabric (eBGP unnumbered + BFD)

```mermaid
flowchart TD
  SP1["spine1 (d3l-29)<br/>AS 65501<br/>system0 192.0.2.2/32"]
  SP2["spine2 (d3l-30)<br/>AS 65502<br/>system0 192.0.2.1/32"]

  SP1 == "e1-31.0 &lt;-&gt; e1-31.0<br/>IPv6 RAv6 unnumbered + BFD" === SP2
  SP1 == "e1-32.0 &lt;-&gt; e1-32.0<br/>IPv6 RAv6 unnumbered + BFD" === SP2

  note["default network-instance:<br/>eBGP dynamic neighbors on e1-31/32<br/>AFI/SAFI: IPv4, IPv6, EVPN<br/>vxlan0 = single VTEP per spine"]
  SP1 -.- note
  SP2 -.- note

  classDef spine fill:#2da44e,stroke:#0b6b2e,color:#fff;
  classDef meta fill:#30363d,stroke:#8b949e,color:#fff;
  class SP1,SP2 spine;
  class note meta;
```

**What it does.** Two physical links (`e1-31`, `e1-32`) tie the spines together.
They run **eBGP** (each spine is its own AS: 65501 / 65502) to exchange the
loopback prefixes in `system0` (`192.0.2.2/32`, `192.0.2.1/32`). Those loopbacks
are the **VTEP** addresses every VXLAN tunnel is sourced from.

**Why these are best practices.**

- **eBGP underlay (not OSPF/iBGP):** eBGP is simple, scales horizontally, gives
  loop-free paths by AS-path, and is the IETF/operator-standard underlay for
  EVPN fabrics. One protocol carries both underlay (IPv4/IPv6) and overlay
  (EVPN) address families — fewer moving parts.
- **"Unnumbered" (IPv6 link-local + Router Advertisement):** no need to plan,
  assign, or document a /31 on every fabric link. BGP auto-discovers the
  neighbor over the link-local address. Less config, fewer mistakes, trivial to
  add links.
- **Two parallel ISLs:** ECMP bandwidth *and* redundancy. Either link can fail
  without isolating a spine.
- **BFD:** sub-second failure detection. Without it, BGP would wait tens of
  seconds (hold timer) to notice a dead link; BFD drops that to milliseconds so
  traffic reconverges fast.
- **Single `vxlan0` VTEP per spine:** all services share one tunnel endpoint,
  keeping the data plane simple.

**How it interacts with the rest.** This layer is the *foundation*: the EVPN
routes in diagram 3 are only useful because the underlay here makes the remote
spine's VTEP reachable. No underlay reachability → no overlay.

## 2 — Access & EVPN Multihoming (all-active vs single-active)

```mermaid
flowchart TD
  SP1["spine1<br/>e1-25 e1-26 e1-29 e1-23"]
  SP2["spine2<br/>e1-25 e1-26 e1-30 e1-23"]

  TOR1["tor1<br/>lag1 (e1-51/52)"]
  TOR2["tor2<br/>lag2 (e1-51/52)"]
  TOR3["tor3<br/>lag3 (e1-29/30)"]
  S3["s3 host<br/>bond0 (eth1+eth2)"]

  SP1 == "lag1" === TOR1
  SP2 == "lag1" === TOR1
  SP1 == "lag2" === TOR2
  SP2 == "lag2" === TOR2
  SP1 == "lag3" === TOR3
  SP2 == "lag3" === TOR3

  S3 == "eth1 ACTIVE/DF" ==> SP1
  S3 -. "eth2 STANDBY" .-> SP2

  es1["ES tor1: ESI 00:00:00:00:00:00:12:00:00:00<br/>all-active, DF default, VLAN 50"]
  es2["ES tor2: all-active, untagged VLAN 10"]
  es3["ES tor3: all-active, VLAN 70"]
  es4["ES tor4/s3: ESI 00:00:00:12:00:00:00:00:00:00<br/>single-active, pref 800 non-revertive,<br/>standby-signaling-on-non-df, VLAN 40 + untagged 10"]

  TOR1 -.- es1
  TOR2 -.- es2
  TOR3 -.- es3
  S3 -.- es4

  classDef spine fill:#2da44e,stroke:#0b6b2e,color:#fff;
  classDef tor fill:#8957e5,stroke:#4b2a8a,color:#fff;
  classDef host fill:#1f6feb,stroke:#0b3d91,color:#fff;
  classDef meta fill:#30363d,stroke:#8b949e,color:#fff;
  class SP1,SP2 spine;
  class TOR1,TOR2,TOR3 tor;
  class S3 host;
  class es1,es2,es3,es4 meta;
```

**What it does.** Every access device (the three ToRs and host `s3`) connects to
*both* spines as a single logical LAG. EVPN multihoming makes two independent
spines behave like one LACP peer, using a shared **Ethernet Segment Identifier
(ESI)** per bundle. There is **no MLAG peer-link** — the spines coordinate purely
over EVPN BGP.

**The two modes shown (and why both exist):**

- **all-active (tor1/tor2/tor3):** both spine links forward at the same time.
  The host/ToR gets the *sum* of both links' bandwidth and instant failover.
  This is the default best practice for throughput.
- **single-active (s3 / `lag4`):** only one link forwards; the other is held
  **standby** and takes over on failure. Used when the attached device or
  application cannot tolerate receiving the same flow from two paths, or when
  strict active/standby is required. The config proves the harder mode works:
  `preference 800`, `non-revertive` (don't flap back automatically), and
  `standby-signaling-on-non-df` (tell the host via LACP to keep the backup link
  down until needed).

**Why these are best practices.**

- **ESI multihoming over MLAG:** standards-based (RFC 7432), no proprietary
  peer-link to size or fail, and it scales to more than two switches.
- **DF (Designated Forwarder) election:** for each Ethernet Segment, exactly one
  spine is elected to forward BUM (broadcast/unknown/multicast) traffic to the
  host, preventing duplicate frames. **Split-horizon** (via the ESI) stops a
  frame the host sent from looping back to it through the other spine.
- **The host stays dumb:** `s3` runs a *standard* 802.3ad bond and is completely
  unaware two switches are involved — no special host software.

**How it interacts with the rest.** This layer maps **physical ports → logical
LAGs → Ethernet Segments**. Those LAGs are then placed into the L2 services in
diagram 3 (e.g. `lag1.50` lands in `macvrf-v50`). Multihoming is the redundancy
plumbing; the services are what ride on top of it.

## 3 — EVPN Service Stack (L2 MAC-VRF + L3 IP-VRF, on the spines)

```mermaid
flowchart LR
  subgraph L2["L2 services - MAC-VRF (EVPN-VXLAN)"]
    direction TB
    V10["macvrf-v10<br/>VLAN 10 · VNI 10010 · EVI 10 · RT 1:10"]
    V20["macvrf-v20<br/>VLAN 20 · VNI 10020 · EVI 20 · RT 1:20"]
    V30["macvrf-v30<br/>VLAN 30 · VNI 10030 · EVI 30 · RT 1:30"]
    V40["macvrf-v40<br/>VLAN 40 · VNI 10040 · EVI 40 · RT 1:40"]
    V50["macvrf-v50<br/>VLAN 50 · VNI 10050 · EVI 50 · RT 1:50"]
    V70["macvrf-v70<br/>VLAN 70 · VNI 10070 · EVI 70 · RT 1:70"]
  end

  subgraph GW["Anycast gateways - irb0 (vrid 1)"]
    direction TB
    I10["irb0.4 v10<br/>172.16.10.254/24"]
    I20["irb0.3 v20<br/>172.16.20.254/24"]
    I30["irb0.0 v30<br/>172.16.30.254/24"]
    I40["irb0.5 v40<br/>172.16.40.254/24"]
    I50["irb0.2 v50<br/>172.16.50.254/24"]
    I70["irb0.1 v70<br/>172.16.70.254/24"]
  end

  VRF["IP-VRF vrf1<br/>VNI 10500 · EVI 500 · RT 1:500<br/>symmetric IRB routing"]

  V10 --- I10
  V20 --- I20
  V30 --- I30
  V40 --- I40
  V50 --- I50
  V70 --- I70
  I10 --> VRF
  I20 --> VRF
  I30 --> VRF
  I40 --> VRF
  I50 --> VRF
  I70 --> VRF

  classDef l2 fill:#1f6feb,stroke:#0b3d91,color:#fff;
  classDef gw fill:#bf8700,stroke:#7a5600,color:#fff;
  classDef vrf fill:#cf222e,stroke:#82071e,color:#fff;
  class V10,V20,V30,V40,V50,V70 l2;
  class I10,I20,I30,I40,I50,I70 gw;
  class VRF vrf;
```

**What it does — read it bottom-up as three layers:**

1. **MAC-VRF (L2 broadcast domain):** each VLAN gets its own MAC-VRF bridge
   table, mapped to a **VXLAN VNI** and an **EVI** (EVPN instance). MAC
   addresses learned locally are advertised to the other spine as **EVPN Type-2
   routes**, so a MAC behind one spine is reachable from the other. The **Route
   Target (RT)** controls which VRFs import those routes — it's the "membership
   tag" that keeps tenants/segments separate.
2. **IRB anycast gateway (L2↔L3 boundary):** `irb0.x` gives each VLAN a default
   gateway IP (e.g. `172.16.10.254`). It's an **anycast** gateway — *both* spines
   answer on the same IP and MAC, so a host's default gateway is always one hop
   away regardless of which spine it lands on, and gateway failover is instant.
3. **IP-VRF (L3 routing domain):** `vrf1` routes *between* those VLANs/subnets.
   Inter-subnet traffic is encapsulated to VNI `10500` (**symmetric IRB**), so
   routing scales without every spine needing every other subnet's IRB.

**Why these are best practices.**

- **VLAN→VNI 1:1 mapping with a clear numbering scheme** (VLAN 10 → VNI 10010,
  EVI 10, RT 1:10): predictable, auditable, easy to automate.
- **EVPN control plane (not flood-and-learn VXLAN):** MACs and IP/MAC bindings
  are *advertised* via BGP, not discovered by flooding. Less broadcast, faster
  convergence, built-in ARP/ND suppression and proxy.
- **Anycast gateway:** removes the classic FHRP (VRRP/HSRP) active/standby
  gateway bottleneck — every spine is the gateway simultaneously.
- **Symmetric IRB:** the scalable way to do L3 in EVPN; only the source and
  destination VRFs need the route, not every transit node.

**How it interacts with the rest.** The **LAGs from diagram 2** are the access
ports that get bound into these MAC-VRFs (L2). The **IRBs** bridge those L2
domains up into **`vrf1`** for L3. And all of it is only reachable because the
**underlay in diagram 1** carries the EVPN routes between the spine VTEPs.

## 4 — Endpoint Connectivity (Linux hosts, with edges)

```mermaid
flowchart TD
  S1["s1<br/>eth1 v10 untagged<br/>eth1.20 v20<br/>eth1.100 v100 routed"]
  S2["s2<br/>eth1.10 v10<br/>eth1.30 v30<br/>eth1.100 v100 routed"]
  S3["s3<br/>bond0 802.3ad<br/>untagged v10 + .40 v40"]
  S4["s4<br/>eth1.50 v50"]
  S5["s5<br/>eth1 untagged v10"]
  S6["s6<br/>eth1.70 v70"]

  SP1["spine1"]
  SP2["spine2"]
  TOR1["tor1"]
  TOR2["tor2"]
  TOR3["tor3"]

  S1 -- "e1-27" --> SP1
  S2 -- "e1-29" --> SP2
  S3 == "e1-23 ACTIVE" ==> SP1
  S3 -. "e1-23 STANDBY" .-> SP2
  S4 -- "tor1 e1-55" --> TOR1
  S5 -- "tor2 e1-56" --> TOR2
  S6 -- "tor3 e1-32" --> TOR3

  L3["Routed L3 access (e1-27.100):<br/>172.16.100.2/31 · 2001:db8:0:100::2/127"]
  SP1 -.- L3

  classDef host fill:#1f6feb,stroke:#0b3d91,color:#fff;
  classDef spine fill:#2da44e,stroke:#0b6b2e,color:#fff;
  classDef tor fill:#8957e5,stroke:#4b2a8a,color:#fff;
  classDef meta fill:#30363d,stroke:#8b949e,color:#fff;
  class S1,S2,S3,S4,S5,S6 host;
  class SP1,SP2 spine;
  class TOR1,TOR2,TOR3 tor;
  class L3 meta;
```

**What it does.** Shows the *five access patterns* the design deliberately
validates with real hosts:

- **L2 untagged** (`s5` eth1 → VLAN 10).
- **L2 tagged** (`s4` eth1.50 → VLAN 50; `s6` eth1.70 → VLAN 70).
- **L3 routed access** (`s1`/`s2` eth1.100 → routed subinterface
  `172.16.100.2/31`, dual-stack).
- **all-active multihoming** (the ToR-attached hosts via diagram 2's ESI-LAGs).
- **single-active multihoming** (`s3` bond0 across both spines).

**Why this matters as a validated design.** A design is only trustworthy if it
proves the *awkward* cases, not just the happy path. By including orphan
single-homed hosts (`s1`/`s2`), a dual-homed bond (`s3`), tagged, untagged, and
routed access all in one lab, every common real-world attachment style is
exercised against the same fabric.

**How it interacts with the rest.** Each host's VLAN here is the *entry point*
into a MAC-VRF in diagram 3, reachable with redundancy via the multihoming in
diagram 2, transported between spines by the underlay in diagram 1. End to end:
**host VLAN → MAC-VRF (L2) → IRB anycast GW → IP-VRF (L3) → VXLAN over eBGP
underlay → remote spine → destination host.**

## How the four layers fit together

```mermaid
flowchart LR
  U["1 · Underlay<br/>eBGP unnumbered + BFD<br/>(VTEP reachability)"]
  M["2 · Multihoming<br/>ESI-LAGs, DF election<br/>(redundant access)"]
  S["3 · Services<br/>MAC-VRF + IRB + IP-VRF<br/>(L2/L3 overlay)"]
  E["4 · Endpoints<br/>tagged/untagged/routed<br/>(host attachment)"]
  U --> S
  M --> S
  S --> E
  classDef b fill:#30363d,stroke:#8b949e,color:#fff;
  class U,M,S,E b;
```

- **Underlay** makes VTEPs reachable so the **Services** overlay can exchange
  EVPN routes.
- **Multihoming** provides the redundant access ports that the **Services** bind
  into MAC-VRFs.
- **Services** present L2 domains and L3 gateways that the **Endpoints** plug
  into.
- Remove any lower layer and everything above it stops working — which is why
  the build order (1 → 2 → 3 → 4) is also the right deployment/automation order.

