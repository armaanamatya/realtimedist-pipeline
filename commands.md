# Commands

Useful commands for testing the COSC 4331 three-node pipeline.

## Python Setup

Run all Python setup commands from the project folder:

```powershell
cd C:\Users\Armaan\Desktop\4331project
```

Create a virtual environment if `venv` does not already exist:

```powershell
python -m venv venv
```

Activate the virtual environment:

```powershell
.\venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, run this once in the same PowerShell window, then activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
```

Install the Python packages from `requirements.txt`:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

You can also install using the venv Python directly without activating:

```powershell
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

Check that PyTorch can see the GPU:

```powershell
.\venv\Scripts\python.exe -c "import torch; print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU only')"
```

Node B will download the HuggingFace model `superb/wav2vec2-base-superb-ks` on first run if it is not already cached. Internet access is needed for that first download.

## Working VxWorks Smoke Test

This is the path that worked:

```text
VxWorks Node A -> Python Node B -> Python Node C host fallback
```

Node A is the VxWorks DKM running in VxSim. Node B and Node C run on the Windows host.

## Start Node C

Run this first in a PowerShell terminal:

```powershell
cd C:\Users\Armaan\Desktop\4331project
.\venv\Scripts\python.exe nodeC_host.py --local --run-id vxworks_smoke
```

Node C listens on UDP port `5002`.

## Start Node B

Run this in a second PowerShell terminal:

```powershell
cd C:\Users\Armaan\Desktop\4331project
.\venv\Scripts\python.exe nodeB.py --local --precision fp32 --confidence-threshold 0.30 --run-id vxworks_smoke
```

Notes:

- `--local` makes Node B bind to `0.0.0.0:5001`, which receives packets from VxSim.
- `--confidence-threshold 0.30` is for smoke testing because `test_audio.wav` produced `stop` confidence around `0.33` to `0.41`.
- For report/default behavior, use the normal threshold by omitting `--confidence-threshold 0.30`.

Default-threshold command:

```powershell
.\venv\Scripts\python.exe nodeB.py --local --precision fp32 --run-id vxworks_fp32_default
```

FP16 comparison command:

```powershell
.\venv\Scripts\python.exe nodeB.py --local --precision fp16 --confidence-threshold 0.30 --run-id vxworks_fp16_smoke
```

## Load Node A DKM In VxWorks

In the VxWorks shell, load the DKM:

```c
ld(1, 0, "/host.host/C:/WindRiver/workbench-4/workspace/nodeA_tasks/vsb_vxsim_windows_SIMNTllvm_LP64_LARGE_SMP/nodeA_tasks/Debug/nodeA_tasks.out")
```

If the symbol is already loaded, you can skip this step.

Check that the entry point exists:

```c
lkup "nodeA_start"
```

Expected result should include something like:

```text
nodeA_start        0x... text (nodeA_tasks.out)
```

## Start Node A In VxWorks

Start the VxWorks Node A tasks:

```c
nodeA_start("/host.host/C:/Users/Armaan/Desktop/4331project/test_audio.wav")
```

Or use the built-in default path:

```c
nodeA_start(0)
```

Expected VxWorks output:

```text
Node A starting
nodeA: opened WAV file: /host.host/C:/Users/Armaan/Desktop/4331project/test_audio.wav
tAudioSample: started period=10ms prio=100
tFeatureExtract: started period=20ms prio=110
tUdpTransmit: started period=20ms prio=120
tUdpTransmit: sending to 172.17.48.234:5001
```

## Stop Or Restart Node A

Stop Node A:

```c
nodeA_stop()
```

Restart Node A:

```c
nodeA_stop()
nodeA_start("/host.host/C:/Users/Armaan/Desktop/4331project/test_audio.wav")
```

Check status:

```c
nodeA_status()
```

## Expected End-To-End Output

Node B should show it is receiving audio and forwarding STOP commands:

```text
nodeB: Listening on 0.0.0.0:5001
nodeB: Sending to 127.0.0.1:5002
inference: stop       conf=0.348 time=7.6ms cmd=STOP fwd=True
```

Node C should receive the forwarded commands and trigger after debounce:

```text
nodeC: recv #448 cmd=STOP conf=0.348
nodeC: recv #450 cmd=STOP conf=0.354
*** ACTUATOR: EMERGENCY_STOP ***
```

## Quick Packet Listener

Use this before Node B if you only want to verify that VxWorks Node A is sending UDP packets to the host:

```powershell
cd C:\Users\Armaan\Desktop\4331project
.\venv\Scripts\python.exe test_listener.py
```

Then start Node A in VxWorks:

```c
nodeA_start("/host.host/C:/Users/Armaan/Desktop/4331project/test_audio.wav")
```

Expected listener output:

```text
Listening on 0.0.0.0:5001...
Packet #0 | ... | 16000 samples | ... | from ...
```

## Common Issues

If VxWorks says this:

```text
C interp: unknown symbol name 'nodeA_start'
```

The DKM is not loaded yet. Run the `ld(1, 0, "...nodeA_tasks.out")` command above, then run:

```c
lkup "nodeA_start"
```

If Node C only prints watchdog fail-safe messages, Node B is probably not forwarding commands because the confidence threshold is too high. For smoke testing, run Node B with:

```powershell
.\venv\Scripts\python.exe nodeB.py --local --precision fp32 --confidence-threshold 0.30 --run-id vxworks_smoke
```

If Node B is not receiving packets, confirm Node A is sending to the host IP in the VxWorks output:

```text
tUdpTransmit: sending to 172.17.48.234:5001
```

On Windows, confirm that host IP exists:

```powershell
Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -eq '172.17.48.234' }
```

## Result Folders

The commands above write results into:

```text
results\vxworks_smoke
results\vxworks_fp16_smoke
results\vxworks_fp32_default
```
