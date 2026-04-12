# Node A Setup Challenges

Date: 2026-04-12

## Context

This document records the setup work completed for Node A of the real-time distributed NLP inference project. Node A is the VxWorks/VxSim audio acquisition and UDP transmit node. The goal of this setup session was to create and boot a VxWorks simulator image, then prepare for a Downloadable Kernel Module (DKM) containing the Node A tasks.

## Installed Wind River Version

The Wind River installation was checked under:

```text
C:\WindRiver
```

The installed platform is:

```text
VxWorks: 21.07
VxWorks platform: vxworks-7
Workbench: Wind River Workbench 4
Install base: C:\WindRiver\vxworks\21.07
```

The command used to confirm the environment was:

```powershell
C:\WindRiver\wrenv.exe -p vxworks/21.07 -o print_env
```

Important output:

```text
WIND_HOME=C:\WindRiver
WIND_BASE=C:\WindRiver\vxworks\21.07
WIND_PLATFORM=vxworks-7
WIND_RELEASE_ID=21.07
WIND_TOOLS=C:\WindRiver\workbench-4
```

This confirmed that the project should follow the VxWorks 7 flow, not the older VxWorks 6.9 flow.

## Simulator Tools Found

The VxSim executable and simulator networking daemon were present:

```text
C:\WindRiver\vxworks\21.07\host\x86-win32\bin\vxsim.exe
C:\WindRiver\vxworks\21.07\host\x86-win32\bin\vxsimnetd.exe
```

The VxSim Windows BSP was also present:

```text
C:\WindRiver\vxworks\21.07\os\board\wrs\vxsim\windows
```

The BSP name appeared as:

```text
vxsim_windows
vxsim_windows_2_0_1_1
```

These refer to the VxSim Windows target family for this installation.

## VxWorks Image Project Creation

A new VxWorks Image Project (VIP) was needed for Node A. Instead of creating the project entirely from scratch through the wizard, the project was created by copying the Wind River prebuilt VxSim Windows LLVM image project.

Source project:

```text
C:\WindRiver\vxworks\21.07\samples\prebuilt_projects\vip_vxsim_windows_llvm\vip_vxsim_windows_llvm.wpj
```

New Node A image project:

```text
C:\WindRiver\workbench-4\workspace\nodeA_vip\nodeA_vip.wpj
```

Workbench reported:

```text
Project copied in : C:/WindRiver/workbench-4/workspace/nodeA_vip/nodeA_vip.wpj
```

The project already existed in the Workbench workspace after creation, so importing it again was not needed. In the import wizard, Workbench displayed the warning:

```text
Some projects cannot be imported because they already exist in the workspace
```

This meant the project was already available in Project Explorer and could be built directly.

## Build Issue: Application Control Blocking touch.exe

The first build of `nodeA_vip` failed because Windows Application Control blocked Wind River's bundled `touch.exe` utility.

Blocked executable:

```text
C:\WindRiver\vxworks\21.07\host\msys2-x86-win64\usr\bin\touch.exe
```

Error pattern:

```text
process_begin: CreateProcess(...\touch.exe, touch versionTag, ...) failed.
make (e=4551): An Application Control policy has blocked this file.
make: *** [C:/WindRiver/vxworks/21.07/build/mk/krnl/rules.vxWorks.mk:210: versionTag] Error 4551
```

The build failed at first when it attempted to create:

```text
versionTag
```

Additional build stamp files were also expected later, so the following files were manually created with PowerShell:

```powershell
New-Item -ItemType File -Force C:\WindRiver\workbench-4\workspace\nodeA_vip\default\versionTag
New-Item -ItemType File -Force C:\WindRiver\workbench-4\workspace\nodeA_vip\default\_user_objs.nm
New-Item -ItemType File -Force C:\WindRiver\workbench-4\workspace\nodeA_vip\default\_user_objs.cdf
New-Item -ItemType File -Force C:\WindRiver\workbench-4\workspace\nodeA_vip\recalc.tm
```

After these files were created, the Workbench build succeeded.

The successful build produced:

```text
C:\WindRiver\workbench-4\workspace\nodeA_vip\default\vxWorks
C:\WindRiver\workbench-4\workspace\nodeA_vip\default\vxWorks.sym
```

Workbench reported:

```text
Build Finished in Project 'nodeA_vip'
```

## VxSim Connection Setup

A VxWorks Simulator connection was created in Workbench.

Connection choices:

```text
Target Type: VxWorks Simulator
Connection Mode: Application Mode
Kernel Image: C:\WindRiver\workbench-4\workspace\nodeA_vip\default\vxWorks
Connect on finish: checked
Start debugger after connect: unchecked
```

It was important to point the Kernel Image to the new Node A image project, not the original Wind River sample project.

Correct image:

```text
C:\WindRiver\workbench-4\workspace\nodeA_vip\default\vxWorks
```

Incorrect image that was initially shown by Workbench:

```text
C:\WindRiver\vxworks\21.07\samples\prebuilt_projects\vip_vxsim_windows_llvm\default\vxWorks
```

## VxSim Boot Result

The simulator booted successfully. It checked the license, loaded the kernel image, mounted the RAM disk, loaded the symbol table, and reached the VxWorks shell prompt:

```text
->
```

One message appeared during use:

```text
Shell task 'tShell0' restarted...
```

However, the shell returned to the prompt afterward, so the simulator was still usable.

## Network Verification

The `ifShow` command was run in the VxWorks shell:

```text
-> ifShow
```

The output showed loopback and VxSim NAT networking:

```text
lo0 <UP RUNNING LOOPBACK MULTICAST NOARP ALLMULTI >
        127.0.0.1

simnet_nat0 <UP RUNNING SIMPLEX BROADCAST MULTICAST >
        10.0.10.2
```

This confirmed that the simulator's network interface was active. The current network mode is NAT using `10.0.10.2`, rather than the planned static `192.168.200.1` address from the original project guide. For future testing, the Node B host address may need to be adjusted or the simnet configuration may need to be changed.

## Task Verification

The `i` command was run in the VxWorks shell:

```text
-> i
```

The output showed active VxWorks tasks including:

```text
tShell0
tNet0
tNetConf
tIdleTask0
tIdleTask1
```

This confirmed that the kernel image was running and the network-related tasks existed.

## DKM Project Creation

After the VxWorks image booted successfully, a new Downloadable Kernel Module project was created for the Node A task code.

Project:

```text
nodeA_tasks
```

Location:

```text
C:\WindRiver\workbench-4\workspace\nodeA_tasks
```

The project was based on the prebuilt VxSim Windows source build project:

```text
C:\WindRiver\vxworks\21.07\samples\prebuilt_projects\vsb_vxsim_windows
```

Workbench created a starter source file:

```text
C:\WindRiver\workbench-4\workspace\nodeA_tasks\dkm.c
```

The starter file only contained an empty `start()` function, so it still needs to be replaced with the Node A task implementation.

## Current Status

Completed:

```text
1. Confirmed Wind River / VxWorks version.
2. Confirmed VxWorks 21.07 and Workbench 4.
3. Created Node A VxWorks Image Project: nodeA_vip.
4. Worked around Application Control build issue by manually creating stamp files.
5. Built the VxWorks image successfully.
6. Created and launched a VxWorks Simulator Application Mode connection.
7. Verified the VxWorks shell prompt.
8. Verified networking with ifShow.
9. Verified active VxWorks tasks with i.
10. Created the Node A DKM project: nodeA_tasks.
```

Remaining:

```text
1. Paste Node A task code into nodeA_tasks\dkm.c.
2. Build nodeA_tasks to generate the DKM .out file.
3. Load the .out file into the running VxSim shell.
4. Run nodeA_start with the WAV file path.
5. Start Node B listener/inference on the host and confirm UDP packets arrive.
6. Adjust Node B IP address if NAT networking requires a different destination than 192.168.200.2.
```

## Report Notes

The main challenge was not VxWorks project creation itself, but the host security environment. Windows Application Control blocked a required Unix-style utility (`touch.exe`) inside the Wind River toolchain. Because the build system uses `touch` to create intermediate stamp files, the VIP build failed even though the compiler and linker were otherwise working. Manually creating the expected stamp files allowed the build to proceed to completion. For a cleaner long-term setup, the blocked Wind River utility should be allowed by the system's application control policy, or the project should be built on a lab machine where Wind River tools are already permitted.

Another setup observation was that the simulator used NAT networking with IP `10.0.10.2`, while the project guide assumed a static simnet address like `192.168.200.1`. This is not a blocker for booting Node A, but it may affect later UDP communication with Node B. The project can either adapt the Node B destination IP for the NAT setup or later reconfigure VxSim networking to match the original simnet plan.
