# Node A Setup Guide — VxSim (Audio Sensor Node)

---

## STEP 0: Ask Your Professor These Questions First

Before you touch anything, send your professor this message or ask in office hours.
You cannot proceed without answers to these:

```
Hey Professor,

For my project I'll be using VxSim to simulate two embedded nodes.
A few quick questions:

1. Which VxWorks version does the course use? (VxWorks 7 or 6.9?)
2. Is Wind River Workbench available through the lab machines or
   do I need to install it on my own machine?
3. If I need to install it, is there a course license key or
   do I use the academic/evaluation license?
4. Are there any lab setup instructions or a getting-started
   guide you can point me to?

Thanks!
```

WHY THIS MATTERS:
- VxWorks 7 vs 6.9 have completely different project workflows
- VxWorks is commercial software ($$$), you NEED a license from the course
- Some courses have it pre-installed on lab machines, others give you a download link
- The networking setup (simnet) differs between versions


---

## STEP 1: Install Wind River Workbench

### Actual setup used on this machine

Wind River is already installed at:

```text
C:\WindRiver
```

The installed version was verified with:

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

Use the VxWorks 7 / 21.07 flow for this project. Do not use the VxWorks 6.9 steps for this machine.

The simulator tools are present at:

```text
C:\WindRiver\vxworks\21.07\host\x86-win32\bin\vxsim.exe
C:\WindRiver\vxworks\21.07\host\x86-win32\bin\vxsimnetd.exe
```

### If your course provides lab machines with VxWorks pre-installed:
- Just log in, open Wind River Workbench, skip to Step 2

### If you need to install on your own Windows machine:

**For VxWorks 7 (more likely if course is recent):**
1. Go to Wind River's download portal (your professor should provide credentials)
2. Download "Wind River Workbench" installer for Windows
3. Run the installer — default paths are fine (typically `C:\WindRiver`)
4. During install, make sure "VxWorks Simulator (VxSim)" is checked
5. Make sure "simnet" networking component is included
6. Apply your license key when prompted

**For VxWorks 6.9:**
1. Download Tornado / Wind River Workbench 3.x installer
2. Install to `C:\WindRiver`
3. VxSim is included by default
4. Apply license

**Verify installation:**
- Open Wind River Workbench
- You should see a "Welcome" tab
- Go to Window > Preferences > Wind River > VxWorks — you should see the VxWorks install path


---

## STEP 2: Create a VxWorks Image with Networking (VxSim BSP)

This is where you build a VxWorks kernel image that will run inside VxSim
with networking enabled.

### Actual VxWorks 21.07 flow used on this machine

For this setup, the working route was to copy Wind River's prebuilt VxSim Windows LLVM image project and use it as the Node A image project.

The project copy command was:

```powershell
C:\WindRiver\vxworks\21.07\host\x86-win64\bin\vxprj.bat vip copy C:/WindRiver/vxworks/21.07/samples/prebuilt_projects/vip_vxsim_windows_llvm/vip_vxsim_windows_llvm.wpj C:/WindRiver/workbench-4/workspace/nodeA_vip/nodeA_vip.wpj
```

Workbench reported:

```text
Project copied in : C:/WindRiver/workbench-4/workspace/nodeA_vip/nodeA_vip.wpj
```

The Node A VxWorks Image Project is:

```text
C:\WindRiver\workbench-4\workspace\nodeA_vip\nodeA_vip.wpj
```

If Workbench says the project cannot be imported because it already exists in the workspace, that is OK. Cancel the import dialog and find `nodeA_vip` in Project Explorer.

Build it from Workbench:

```text
Right-click nodeA_vip > Build Project
```

On this machine, the first build failed because Windows Application Control blocked Wind River's bundled `touch.exe`:

```text
C:\WindRiver\vxworks\21.07\host\msys2-x86-win64\usr\bin\touch.exe
```

The workaround was to manually create the stamp files:

```powershell
New-Item -ItemType File -Force C:\WindRiver\workbench-4\workspace\nodeA_vip\default\versionTag
New-Item -ItemType File -Force C:\WindRiver\workbench-4\workspace\nodeA_vip\default\_user_objs.nm
New-Item -ItemType File -Force C:\WindRiver\workbench-4\workspace\nodeA_vip\default\_user_objs.cdf
New-Item -ItemType File -Force C:\WindRiver\workbench-4\workspace\nodeA_vip\recalc.tm
```

After rebuilding, the image was created successfully:

```text
C:\WindRiver\workbench-4\workspace\nodeA_vip\default\vxWorks
C:\WindRiver\workbench-4\workspace\nodeA_vip\default\vxWorks.sym
```

### Generic VxWorks 7 flow (reference only)

1. Open Wind River Workbench
2. File > New > VxWorks Source Build Project
3. Select BSP: **vxsim_windows** (this is the VxSim simulator BSP)
4. Name the project: `nodeA_vxsim`
5. In the kernel configuration panel, make sure these components are INCLUDED:

```
INCLUDE_NETWORK            — base networking
INCLUDE_IPNET              — IP stack
INCLUDE_IFCONFIG           — interface configuration
INCLUDE_SIMNET             — simnet virtual NIC (THIS IS CRITICAL)
INCLUDE_UDP                — UDP sockets
INCLUDE_POSIX_TIMERS       — for timing
INCLUDE_SEM_MUTEX          — for ring buffer sync
INCLUDE_MSG_Q              — message queues
INCLUDE_TASK_CREATE_HOOKS  — task instrumentation
INCLUDE_TIMESTAMP          — high-res timestamps
INCLUDE_SHELL              — kernel shell (for debugging)
INCLUDE_RTP                — real-time processes (optional)
```

6. Build the VxWorks image: Project > Build Project
7. This produces a `vxWorks` binary in the project's output directory

### VxWorks 6.9 Flow:

1. Open Workbench
2. File > New > VxWorks Image Project
3. BSP: **simpc** or **vxsim** (depends on your install)
4. In the kernel config, include the same components listed above
   (the names may be slightly different, e.g., INCLUDE_NET_INIT)
5. Build


---

## STEP 3: Launch VxSim Instance 0 (Node A)

### Actual Workbench connection used on this machine

Create a VxWorks Simulator connection with:

```text
Target Type: VxWorks Simulator
Connection Mode: Application Mode
Kernel Image: C:\WindRiver\workbench-4\workspace\nodeA_vip\default\vxWorks
Connect on finish: checked
Start debugger after connect: unchecked
```

Important: make sure the Kernel Image points to the new `nodeA_vip` image, not the original Wind River sample image.

Correct:

```text
C:\WindRiver\workbench-4\workspace\nodeA_vip\default\vxWorks
```

Incorrect:

```text
C:\WindRiver\vxworks\21.07\samples\prebuilt_projects\vip_vxsim_windows_llvm\default\vxWorks
```

The simulator should boot and reach the VxWorks shell:

```text
->
```

On this machine, `ifShow` showed NAT networking:

```text
-> ifShow
lo0 <UP RUNNING LOOPBACK MULTICAST NOARP ALLMULTI >
        127.0.0.1

simnet_nat0 <UP RUNNING SIMPLEX BROADCAST MULTICAST >
        10.0.10.2
```

This means the simulator is currently using `10.0.10.2` through NAT, not the original planned static `192.168.200.1` simnet address. This may require adjusting the Node B destination IP later.

Task verification:

```text
-> i
```

Expected running tasks include `tShell0`, `tNet0`, `tNetConf`, and idle tasks. If the shell prints `Shell task 'tShell0' restarted...` but returns to the `->` prompt, the simulator is still usable.

### From Wind River Workbench:

1. Right-click on your `nodeA_vxsim` project
2. Select "Connect to VxSim" or "Launch Simulator"
3. In the Target Connection settings:
   - Network device: **simnet**
   - IP address: **192.168.200.1**
   - Subnet mask: **255.255.255.0**
   - Unit number: **0**

### From Command Line (alternative):

Open a Wind River command shell (Start > Wind River > VxWorks Development Shell):

```cmd
cd C:\WindRiver\vxworks-7\...  (your project output directory)

vxsim -p 0 -d simnet -ni 0 -e 192.168.200.1 -sm 255.255.255.0
```

Flags:
  -p 0          → processor number 0 (Node A)
  -d simnet     → use simnet network driver
  -ni 0         → network interface unit 0
  -e 192.168.200.1  → IP address for this instance
  -sm 255.255.255.0 → subnet mask

### Verify it's running:

In the VxWorks kernel shell that opens, type:

```
-> ifShow
```

You should see the simnet interface with IP 192.168.200.1.

```
-> ping "192.168.200.1"
```

Should reply to itself.


---

## STEP 4: Write the Node A Application Code

Create a Downloadable Kernel Module (DKM) project for your Node A tasks.

### In Workbench:

1. File > New > VxWorks Downloadable Kernel Module (DKM)
2. Name: `nodeA_tasks`
3. Create the project in the Workbench workspace
4. Base the project on a source build project
5. Select the prebuilt VSB:

```text
C:\WindRiver\vxworks\21.07\samples\prebuilt_projects\vsb_vxsim_windows
```

Workbench creates the project at:

```text
C:\WindRiver\workbench-4\workspace\nodeA_tasks
```

The generated starter file is:

```text
C:\WindRiver\workbench-4\workspace\nodeA_tasks\dkm.c
```

### Replace the starter file: `dkm.c`

```c
/* nodeA.c — Audio Sensor Node (VxSim Instance 0)
 *
 * Three periodic tasks:
 *   tAudioSample   — reads PCM audio from WAV file (T=10ms)
 *   tFeatureExtract — chunks waveform for inference node (T=20ms)
 *   tUdpTransmit   — sends features over UDP to Node B (T=20ms)
 */

#include <vxWorks.h>
#include <taskLib.h>
#include <semLib.h>
#include <sysLib.h>
#include <tickLib.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

/* Networking */
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>

/* ============================================================
 * CONFIGURATION
 * ============================================================ */
#define SAMPLE_RATE       16000          /* 16 kHz */
#define SAMPLES_PER_READ  160           /* 10ms worth of samples at 16kHz */
#define RING_BUF_SIZE     16000         /* 1 second of audio (16000 samples) */
#define CHUNK_SIZE        16000         /* 1 second chunk for Wav2Vec2 */
#define NODE_B_IP         "172.17.48.234"  /* Windows host Wi-Fi IP used with VxSim NAT */
#define NODE_B_PORT       5001
#define MONITOR_PORT      5100          /* for telemetry logging */

/* Task priorities — lower number = higher priority in VxWorks */
#define PRIO_AUDIO_SAMPLE   100
#define PRIO_FEATURE_EXTRACT 110
#define PRIO_UDP_TRANSMIT    120

/* Task stack sizes */
#define STACK_SIZE  0x10000  /* 64KB */

/* ============================================================
 * SHARED DATA
 * ============================================================ */

/* Ring buffer for audio samples */
static short    ringBuf[RING_BUF_SIZE];
static int      ringHead = 0;
static int      ringTail = 0;
static int      ringCount = 0;
static SEM_ID   ringMutex;

/* Feature chunk ready for transmission */
static short    featureChunk[CHUNK_SIZE];
static int      chunkReady = 0;
static SEM_ID   chunkMutex;

/* WAV file handle */
static FILE*    wavFile = NULL;
static int      wavDataOffset = 0;  /* offset past WAV header */

/* Sequence number for packets */
static unsigned int seqNum = 0;

/* Task IDs */
static TASK_ID  tidAudioSample;
static TASK_ID  tidFeatureExtract;
static TASK_ID  tidUdpTransmit;

/* Running flag */
static volatile BOOL running = TRUE;

/* UDP socket */
static int      udpSock = -1;
static struct sockaddr_in nodeBAddr;

/* ============================================================
 * TIMING HELPERS
 * ============================================================ */

/* Get current time in microseconds (for latency measurement) */
static unsigned long long getTimestampUs(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (unsigned long long)ts.tv_sec * 1000000ULL +
           (unsigned long long)ts.tv_nsec / 1000ULL;
}

/* Periodic task helper — sleeps until next period */
static void waitNextPeriod(int periodMs)
{
    taskDelay(periodMs * sysClkRateGet() / 1000);
}

/* ============================================================
 * WAV FILE READER
 * ============================================================ */

/* Open WAV file and skip header (assumes 16-bit, 16kHz, mono) */
static STATUS openWavFile(const char* path)
{
    wavFile = fopen(path, "rb");
    if (wavFile == NULL)
    {
        printf("nodeA: ERROR — cannot open WAV file: %s\n", path);
        return ERROR;
    }

    /* Skip 44-byte WAV header (standard PCM header) */
    fseek(wavFile, 44, SEEK_SET);
    wavDataOffset = 44;

    printf("nodeA: Opened WAV file: %s\n", path);
    return OK;
}

/* Read samples from WAV, loop back to start when EOF */
static int readWavSamples(short* buf, int numSamples)
{
    int read = fread(buf, sizeof(short), numSamples, wavFile);

    if (read < numSamples)
    {
        /* Loop back to start of audio data */
        fseek(wavFile, wavDataOffset, SEEK_SET);
        int remaining = numSamples - read;
        fread(buf + read, sizeof(short), remaining, wavFile);
        read = numSamples;
    }

    return read;
}

/* ============================================================
 * TASK 1: tAudioSample (Period = 10ms, Priority = 100)
 *
 * Reads 160 samples (10ms @ 16kHz) from WAV file into ring buffer.
 * ============================================================ */
static void tAudioSample(void)
{
    short samples[SAMPLES_PER_READ];
    unsigned long long startTime, endTime;

    printf("tAudioSample: started (period=10ms, prio=%d)\n", PRIO_AUDIO_SAMPLE);

    while (running)
    {
        startTime = getTimestampUs();

        /* Read samples from WAV file */
        readWavSamples(samples, SAMPLES_PER_READ);

        /* Write into ring buffer */
        semTake(ringMutex, WAIT_FOREVER);
        {
            int i;
            for (i = 0; i < SAMPLES_PER_READ; i++)
            {
                ringBuf[ringHead] = samples[i];
                ringHead = (ringHead + 1) % RING_BUF_SIZE;
                if (ringCount < RING_BUF_SIZE)
                    ringCount++;
                else
                    ringTail = (ringTail + 1) % RING_BUF_SIZE; /* overwrite oldest */
            }
        }
        semGive(ringMutex);

        endTime = getTimestampUs();

        /* Log execution time (for analysis) */
        /* printf("tAudioSample: exec=%llu us\n", endTime - startTime); */

        waitNextPeriod(10);
    }
}

/* ============================================================
 * TASK 2: tFeatureExtract (Period = 20ms, Priority = 110)
 *
 * When ring buffer has >= CHUNK_SIZE samples, copies them out
 * as a chunk ready for transmission.
 *
 * For Wav2Vec2: we send raw waveform. The feature extractor
 * runs on Node B (Python side). This keeps Node A lightweight.
 * ============================================================ */
static void tFeatureExtract(void)
{
    unsigned long long startTime, endTime;

    printf("tFeatureExtract: started (period=20ms, prio=%d)\n", PRIO_FEATURE_EXTRACT);

    while (running)
    {
        startTime = getTimestampUs();

        semTake(ringMutex, WAIT_FOREVER);
        {
            if (ringCount >= CHUNK_SIZE)
            {
                /* Copy CHUNK_SIZE samples from ring buffer */
                int i;
                for (i = 0; i < CHUNK_SIZE; i++)
                {
                    featureChunk[i] = ringBuf[(ringTail + i) % RING_BUF_SIZE];
                }

                /* Advance tail */
                ringTail = (ringTail + CHUNK_SIZE) % RING_BUF_SIZE;
                ringCount -= CHUNK_SIZE;

                semTake(chunkMutex, WAIT_FOREVER);
                chunkReady = 1;
                semGive(chunkMutex);
            }
        }
        semGive(ringMutex);

        endTime = getTimestampUs();
        /* printf("tFeatureExtract: exec=%llu us\n", endTime - startTime); */

        waitNextPeriod(20);
    }
}

/* ============================================================
 * TASK 3: tUdpTransmit (Period = 20ms, Priority = 120)
 *
 * Sends the latest feature chunk over UDP to Node B.
 * Packet format:
 *   [seq_num: 4 bytes][timestamp_us: 8 bytes][audio: CHUNK_SIZE * 2 bytes]
 * ============================================================ */

/* Packet header structure */
typedef struct {
    unsigned int    seqNum;
    unsigned long long timestampUs;
} __attribute__((packed)) PacketHeader;

static void tUdpTransmit(void)
{
    unsigned long long startTime, endTime;
    char packetBuf[sizeof(PacketHeader) + CHUNK_SIZE * sizeof(short)];
    PacketHeader* hdr = (PacketHeader*)packetBuf;

    printf("tUdpTransmit: started (period=20ms, prio=%d)\n", PRIO_UDP_TRANSMIT);
    printf("tUdpTransmit: sending to %s:%d\n", NODE_B_IP, NODE_B_PORT);

    while (running)
    {
        startTime = getTimestampUs();

        semTake(chunkMutex, WAIT_FOREVER);
        if (chunkReady)
        {
            /* Build packet */
            hdr->seqNum = seqNum++;
            hdr->timestampUs = getTimestampUs();
            memcpy(packetBuf + sizeof(PacketHeader),
                   featureChunk,
                   CHUNK_SIZE * sizeof(short));

            chunkReady = 0;
            semGive(chunkMutex);

            /* Send UDP datagram */
            int sent = sendto(udpSock, packetBuf,
                              sizeof(PacketHeader) + CHUNK_SIZE * sizeof(short),
                              0,
                              (struct sockaddr*)&nodeBAddr,
                              sizeof(nodeBAddr));

            if (sent < 0)
            {
                printf("tUdpTransmit: sendto failed\n");
            }
        }
        else
        {
            semGive(chunkMutex);
        }

        endTime = getTimestampUs();
        /* printf("tUdpTransmit: exec=%llu us\n", endTime - startTime); */

        waitNextPeriod(20);
    }
}

/* ============================================================
 * INITIALIZATION
 * ============================================================ */

/* Call this function from the VxWorks shell to start Node A:
 *   -> nodeA_start "/path/to/test_audio.wav"
 */
void nodeA_start(const char* wavPath)
{
    printf("\n========================================\n");
    printf("  Node A — Audio Sensor Starting\n");
    printf("========================================\n\n");

    /* Default WAV path */
    if (wavPath == NULL)
    {
        wavPath = "/passFs0/test_audio.wav";
    }

    /* Open WAV file */
    if (openWavFile(wavPath) != OK)
    {
        printf("nodeA: FATAL — cannot open WAV file, aborting\n");
        return;
    }

    /* Create semaphores */
    ringMutex = semMCreate(SEM_Q_PRIORITY | SEM_INVERSION_SAFE);
    chunkMutex = semMCreate(SEM_Q_PRIORITY | SEM_INVERSION_SAFE);

    if (ringMutex == NULL || chunkMutex == NULL)
    {
        printf("nodeA: FATAL — cannot create semaphores\n");
        return;
    }

    /* Create UDP socket */
    udpSock = socket(AF_INET, SOCK_DGRAM, 0);
    if (udpSock < 0)
    {
        printf("nodeA: FATAL — cannot create UDP socket\n");
        return;
    }

    /* Configure Node B address */
    memset(&nodeBAddr, 0, sizeof(nodeBAddr));
    nodeBAddr.sin_family = AF_INET;
    nodeBAddr.sin_port = htons(NODE_B_PORT);
    nodeBAddr.sin_addr.s_addr = inet_addr(NODE_B_IP);

    printf("nodeA: UDP socket created, target=%s:%d\n", NODE_B_IP, NODE_B_PORT);

    /* Spawn tasks */
    printf("nodeA: Spawning tasks...\n");

    running = TRUE;

    tidAudioSample = taskSpawn(
        "tAudioSample",        /* name */
        PRIO_AUDIO_SAMPLE,     /* priority (100 = highest of our tasks) */
        0,                     /* options */
        STACK_SIZE,            /* stack size */
        (FUNCPTR)tAudioSample, /* entry point */
        0,0,0,0,0,0,0,0,0,0   /* 10 args (unused) */
    );

    tidFeatureExtract = taskSpawn(
        "tFeatureExtract",
        PRIO_FEATURE_EXTRACT,
        0,
        STACK_SIZE,
        (FUNCPTR)tFeatureExtract,
        0,0,0,0,0,0,0,0,0,0
    );

    tidUdpTransmit = taskSpawn(
        "tUdpTransmit",
        PRIO_UDP_TRANSMIT,
        0,
        STACK_SIZE,
        (FUNCPTR)tUdpTransmit,
        0,0,0,0,0,0,0,0,0,0
    );

    if (tidAudioSample == TASK_ID_ERROR ||
        tidFeatureExtract == TASK_ID_ERROR ||
        tidUdpTransmit == TASK_ID_ERROR)
    {
        printf("nodeA: FATAL — failed to spawn one or more tasks\n");
        nodeA_stop();
        return;
    }

    printf("\nnodeA: All tasks running!\n");
    printf("  tAudioSample    — prio=%d period=10ms\n", PRIO_AUDIO_SAMPLE);
    printf("  tFeatureExtract — prio=%d period=20ms\n", PRIO_FEATURE_EXTRACT);
    printf("  tUdpTransmit   — prio=%d period=20ms\n", PRIO_UDP_TRANSMIT);
    printf("\n");
}

/* Stop all tasks */
void nodeA_stop(void)
{
    printf("nodeA: Stopping...\n");
    running = FALSE;

    taskDelay(sysClkRateGet() / 2);  /* wait 500ms for tasks to exit */

    if (tidAudioSample != TASK_ID_ERROR)
        taskDelete(tidAudioSample);
    if (tidFeatureExtract != TASK_ID_ERROR)
        taskDelete(tidFeatureExtract);
    if (tidUdpTransmit != TASK_ID_ERROR)
        taskDelete(tidUdpTransmit);

    if (udpSock >= 0)
        close(udpSock);
    if (wavFile != NULL)
        fclose(wavFile);
    if (ringMutex != NULL)
        semDelete(ringMutex);
    if (chunkMutex != NULL)
        semDelete(chunkMutex);

    printf("nodeA: Stopped.\n");
}

/* Show status */
void nodeA_status(void)
{
    printf("\n--- Node A Status ---\n");
    printf("Ring buffer: %d / %d samples\n", ringCount, RING_BUF_SIZE);
    printf("Chunks sent: %u\n", seqNum);
    printf("Running: %s\n", running ? "YES" : "NO");
    printf("---------------------\n\n");
}
```

### Compile and Load:

1. Paste the Node A code into `C:\WindRiver\workbench-4\workspace\nodeA_tasks\dkm.c`
2. Build the project from Workbench: `Right-click nodeA_tasks > Build Project`
3. This produces:

```text
C:\WindRiver\workbench-4\workspace\nodeA_tasks\vsb_vxsim_windows_SIMNTllvm_LP64_LARGE_SMP\nodeA_tasks\Debug\nodeA_tasks.out
```

The DKM build may still print `touch.exe` Application Control warnings, but the build is successful if Workbench prints:

```text
Build Finished in Project 'nodeA_tasks'
```

4. In the VxWorks shell connected to VxSim, load the module:

```
-> ld < "/host.host/C:/WindRiver/workbench-4/workspace/nodeA_tasks/vsb_vxsim_windows_SIMNTllvm_LP64_LARGE_SMP/nodeA_tasks/Debug/nodeA_tasks.out"
```

5. Confirm the module loaded:

```text
-> start
```

Expected output:

```text
nodeA_tasks loaded. Use nodeA_start(path), nodeA_status(), nodeA_stop().
```

6. Start Node A with the test audio file:

```text
-> nodeA_start "/host.host/C:/Users/Armaan/Desktop/4331project/test_audio.wav"
```

In this VxSim setup, the host filesystem path uses `/host.host/C:/...`.


---

## STEP 5: Prepare the Test Audio

You need a WAV file in the right format: 16kHz, 16-bit, mono PCM.

### Option A — Download from Google Speech Commands:
1. Download: https://storage.cloud.google.com/download.tensorflow.org/data/speech_commands_v0.02.tar.gz
2. Extract — you'll find folders like `stop/`, `go/`, `yes/`, `no/`
3. Each file is a 1-second 16kHz WAV clip

### Option B — Create a looping test file:
Use ffmpeg (on your Windows machine or WSL) to concatenate clips:

```bash
# In WSL or with ffmpeg installed on Windows
# Concatenate several "stop" clips with silence between them
ffmpeg -i stop_001.wav -i silence_1s.wav -i stop_002.wav \
       -filter_complex "[0:0][1:0][2:0]concat=n=3:v=0:a=1" \
       -ar 16000 -ac 1 -sample_fmt s16 test_audio.wav
```

### Option C — Generate a simple test tone (for initial debugging):
```bash
# 5 seconds of 440Hz tone at 16kHz sample rate
ffmpeg -f lavfi -i "sine=frequency=440:duration=5" \
       -ar 16000 -ac 1 -sample_fmt s16 test_tone.wav
```

Place the WAV file somewhere on your C: drive that VxSim can access. In this setup, the working path style was `/host.host/C:/...`; for example:

```text
/host.host/C:/Users/Armaan/Desktop/4331project/test_audio.wav
```


---

## STEP 6: Test Node A in Isolation

### Test 1 — Tasks are running:
In the VxWorks shell:
```
-> nodeA_start "/host.host/C:/Users/Armaan/Desktop/4331project/test_audio.wav"
-> i             (shows all tasks and their states)
-> nodeA_status  (shows ring buffer fill level and packets sent)
```

You should see:
- tAudioSample, tFeatureExtract, tUdpTransmit all in READY or DELAY state
- Ring buffer filling up
- Sequence number incrementing

### Test 2 — UDP packets are being sent:
On your Windows host, open a second terminal and run a simple Python UDP listener:

```python
# test_listener.py — run this on your Windows host
import socket
import struct

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("0.0.0.0", 5001))  # Listen on all host interfaces for VxSim NAT

print("Listening for packets from Node A...")

while True:
    data, addr = sock.recvfrom(65536)
    seq = struct.unpack("<I", data[:4])[0]
    ts = struct.unpack("<Q", data[4:12])[0]
    audio_bytes = len(data) - 12
    audio_samples = audio_bytes // 2
    print(f"Packet #{seq} | ts={ts} us | {audio_samples} samples | from {addr}")
```

Run it:
```cmd
python test_listener.py
```

You should see packets arriving every ~20ms with incrementing sequence numbers.

Note for the current Workbench/VxSim setup: `ifShow` showed `simnet_nat0` with IP `10.0.10.2`, while the Windows host Wi-Fi IP was `172.17.48.234`. The working DKM build used `NODE_B_IP = "172.17.48.234"` and Node B was started with `python nodeB.py --local --precision fp32`, which made Node B listen on `0.0.0.0:5001`.

### Test 3 — Verify timing:
```
-> spy    (VxWorks CPU utilization monitor)
```

Check that total CPU usage is reasonable (should be well under 100%).

### Test 4 — Task timing instrumentation:
Uncomment the `printf` lines in each task to see execution times.
You should see:
- tAudioSample: ~1-3ms execution time
- tFeatureExtract: ~1-5ms (depends on how much data is in buffer)
- tUdpTransmit: ~1-3ms per send


---

## STEP 7: Troubleshooting

### Build fails because Application Control blocks `touch.exe`
On this machine, Windows Application Control blocked Wind River's bundled `touch.exe`:

```text
C:\WindRiver\vxworks\21.07\host\msys2-x86-win64\usr\bin\touch.exe
```

The error looks like:

```text
make (e=4551): An Application Control policy has blocked this file.
```

For the `nodeA_vip` image build, manually creating the expected stamp files allowed the build to complete:

```powershell
New-Item -ItemType File -Force C:\WindRiver\workbench-4\workspace\nodeA_vip\default\versionTag
New-Item -ItemType File -Force C:\WindRiver\workbench-4\workspace\nodeA_vip\default\_user_objs.nm
New-Item -ItemType File -Force C:\WindRiver\workbench-4\workspace\nodeA_vip\default\_user_objs.cdf
New-Item -ItemType File -Force C:\WindRiver\workbench-4\workspace\nodeA_vip\recalc.tm
```

For a cleaner long-term setup, Windows security should allow the Wind River toolchain utilities.

### "Cannot create UDP socket"
→ Your VxWorks image doesn't have networking. Rebuild with INCLUDE_NETWORK
  and INCLUDE_SIMNET. Make sure you launched VxSim with `-d simnet`.

### "sendto failed"
→ Check IP addresses. Node A should be 192.168.200.1, Node B should be
  192.168.200.2. Run `ifShow` in VxWorks shell to verify interface config.
→ Check if the Python listener is actually bound to 192.168.200.2

For the current NAT setup, `ifShow` reported Node A as `10.0.10.2`. If UDP packets do not arrive, update the listener and `NODE_B_IP` to match the active VxSim/host network rather than assuming the original `192.168.200.x` plan.

### "cannot open WAV file"
→ Path issue. In VxSim, your Windows C: drive is accessible as `/passFs0/`.
  So `C:\Users\nop\project\test.wav` becomes `/passFs0/Users/nop/project/test.wav`.
  Note: forward slashes, not backslashes.

For the current VxWorks 21.07 simulator connection, the path that worked was `/host.host/C:/...`; for example:

```text
/host.host/C:/Users/Armaan/Desktop/4331project/test_audio.wav
```

### Tasks not running / no output
→ Check `i` command — are tasks in SUSPENDED state?
→ Make sure sysClkRateGet() returns a reasonable value (usually 60 on VxSim).
  If it returns 60, then `taskDelay(60) = 1 second`. The timing math in
  waitNextPeriod() accounts for this.

### "simnet not working / can't ping between instances"
→ Make sure vxsimnetd daemon is running. On some Windows setups you need to
  start it from the Wind River Development Shell:
  ```
  vxsimnetd
  ```
→ Check Windows Firewall — it may block the simnet virtual NIC.


---

## STEP 8: What Comes Next

Once Node A is sending packets reliably:

1. **Node B (next):** Write the Python host process that receives UDP packets,
   runs wav2vec2-base-superb-ks inference on GPU, and sends the result to Node C.
   This runs on your host machine, NOT inside VxSim.

2. **Node C:** Create a second VxSim instance (processor 1, IP 192.168.200.3)
   with tasks for receiving commands, safety validation, and actuation.

3. **Network proxy:** Insert the Python jitter/loss proxy between the UDP streams.

4. **Instrumentation:** Add detailed timestamp logging for end-to-end latency
   measurement across all three nodes.
