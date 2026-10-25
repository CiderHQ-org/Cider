/* CoreAudio HAL additions for FMOD (Roblox audio).
 *
 * Darling's PulseAudio HAL exposes an output device (object 2, also 4 as the
 * system output) and an input device (object 3), but only a few properties.
 * FMOD's CoreAudio output asks the device for its streams ('stm#') first and
 * gave up on "unknown property", so Roblox fell back to "NoSound Driver".
 * This answers the missing device and stream properties with the format
 * Darling's stream really uses (44.1 kHz, stereo, 32-bit float, interleaved)
 * and passes everything else through. QUADRA_TRACE_AUDIO=1 logs the calls.
 *
 * Imports are weak: RobloxCrashHandler loads this library but not CoreAudio. */

typedef int OSStatus;
typedef unsigned int UInt32;
typedef double Float64;
typedef struct { UInt32 selector, scope, element; } PropertyAddress;
typedef struct { UInt32 type, subtype, manufacturer, flags, mask; } ComponentDescription;
typedef struct {
    Float64 sample_rate;
    UInt32 format_id, format_flags, bytes_per_packet, frames_per_packet, bytes_per_frame,
        channels_per_frame, bits_per_channel, reserved;
} StreamDescription;
typedef struct { Float64 minimum, maximum; } ValueRange;
typedef struct { StreamDescription format; ValueRange rates; } RangedDescription;
typedef struct { UInt32 channels, byte_size; void *data; } Buffer;
typedef struct { UInt32 count; Buffer buffers[1]; } BufferList;
typedef void (*ListenerProc)(void);

extern char *getenv(const char *);
extern int snprintf(char *, unsigned long, const char *, ...);
extern long write(int, const void *, unsigned long);

#define W __attribute__((weak_import)) extern
W OSStatus AudioObjectGetPropertyData(UInt32, const PropertyAddress *, UInt32, const void *, UInt32 *, void *);
W OSStatus AudioObjectGetPropertyDataSize(UInt32, const PropertyAddress *, UInt32, const void *, UInt32 *);
W unsigned char AudioObjectHasProperty(UInt32, const PropertyAddress *);
W OSStatus AudioObjectSetPropertyData(UInt32, const PropertyAddress *, UInt32, const void *, UInt32, const void *);
W OSStatus AudioObjectIsPropertySettable(UInt32, const PropertyAddress *, unsigned char *);
W OSStatus AudioObjectAddPropertyListener(UInt32, const PropertyAddress *, ListenerProc, void *);
W OSStatus AudioObjectRemovePropertyListener(UInt32, const PropertyAddress *, ListenerProc, void *);
W void *AudioComponentFindNext(void *, const ComponentDescription *);
W OSStatus AudioComponentInstanceNew(void *, void **);
W OSStatus AudioUnitSetProperty(void *, UInt32, UInt32, UInt32, const void *, UInt32);
W OSStatus AudioUnitGetProperty(void *, UInt32, UInt32, UInt32, void *, UInt32 *);
W OSStatus AudioUnitInitialize(void *);
W OSStatus AudioOutputUnitStart(void *);
W OSStatus AudioDeviceCreateIOProcID(UInt32, void *, void *, void **);
W OSStatus AudioDeviceStart(UInt32, void *);
W OSStatus AudioDeviceStop(UInt32, void *);
W OSStatus AudioDeviceDestroyIOProcID(UInt32, void *);
W OSStatus AudioComponentInstanceDispose(void *);
W OSStatus AudioUnitUninitialize(void *);
W OSStatus AudioOutputUnitStop(void *);
W OSStatus AudioUnitRender(void *, UInt32 *, const void *, UInt32, UInt32, BufferList *);
extern void *calloc(unsigned long, unsigned long);
extern void *malloc(unsigned long);
extern void free(void *);
extern unsigned long long mach_absolute_time(void);

#define DYLD_INTERPOSE(_replacement, _replacee) \
    __attribute__((used)) static struct { const void *replacement; const void *replacee; } \
    _interpose_##_replacee __attribute__((section("__DATA,__interpose"))) = \
        {(const void *)(unsigned long)&_replacement, (const void *)(unsigned long)&_replacee};

#define FOURCC(a, b, c, d) ((UInt32)(a) << 24 | (UInt32)(b) << 16 | (UInt32)(c) << 8 | (UInt32)(d))
#define SCOPE_GLOBAL FOURCC('g', 'l', 'o', 'b')
#define SCOPE_OUTPUT FOURCC('o', 'u', 't', 'p')
#define SCOPE_INPUT FOURCC('i', 'n', 'p', 't')
#define OUTPUT_STREAM 0x4001u
#define INPUT_STREAM 0x4002u
#define NO_ERROR 0
#define BAD_SIZE FOURCC('!', 's', 'i', 'z')
#define UNSUPPORTED_FORMAT FOURCC('!', 'd', 'a', 't')
#define NOT_HANDLED 0x7fffffff

/* ---------------------------------------------------------------- tracing */

static int tracing(void) {
    static int value = -1;
    if (value < 0) {
        const char *text = getenv("QUADRA_TRACE_AUDIO");
        value = text && text[0] && text[0] != '0';
    }
    return value;
}

static void code(char out[8], UInt32 value) {
    for (int i = 0; i < 4; i++) {
        char c = (char)(value >> (24 - 8 * i));
        out[i] = c >= 32 && c < 127 ? c : '?';
    }
    out[4] = 0;
}

static void report(const char *function, UInt32 object, const PropertyAddress *address,
                   long status, UInt32 size, int ours) {
    if (!tracing())
        return;
    char selector[8] = "-", scope[8] = "-", line[200];
    if (address) {
        code(selector, address->selector);
        code(scope, address->scope);
    }
    int length = snprintf(line, sizeof line, "[Quadra Audio] %s object=%u '%s' scope='%s' -> %ld size=%u%s\n",
                          function, object, selector, scope, status, size, ours ? " (shim)" : "");
    if (length > 0)
        write(2, line, (unsigned long)length);
}

/* ------------------------------------------------------ added properties */

static int is_output_device(UInt32 object) { return object == 2 || object == 4; }
static int is_input_device(UInt32 object) { return object == 3; }
static int is_device(UInt32 object) { return is_output_device(object) || is_input_device(object); }
static int is_stream(UInt32 object) { return object == OUTPUT_STREAM || object == INPUT_STREAM; }

static StreamDescription current_format = {
    44100.0, FOURCC('l', 'p', 'c', 'm'), 1 /* float */ | 8 /* packed */, 8, 1, 8, 2, 32, 0};

/* Does the device side of `scope` have a stream on this device? */
static int device_has_stream(UInt32 object, UInt32 scope) {
    if (scope == SCOPE_GLOBAL)
        return 1;
    return (is_output_device(object) && scope == SCOPE_OUTPUT) ||
           (is_input_device(object) && scope == SCOPE_INPUT);
}

static OSStatus put(const void *value, UInt32 size, UInt32 *io_size, void *out) {
    if (out) {
        if (!io_size || *io_size < size)
            return BAD_SIZE;
        const unsigned char *from = value;
        unsigned char *to = out;
        for (UInt32 i = 0; i < size; i++)
            to[i] = from[i];
    }
    if (io_size)
        *io_size = size;
    return NO_ERROR;
}

static OSStatus put_u32(UInt32 value, UInt32 *io_size, void *out) {
    return put(&value, sizeof value, io_size, out);
}

/* QUADRA_AUDIO=0 turns the additions off (FMOD then uses "NoSound"). */
static int additions_enabled(void) {
    static int value = -1;
    if (value < 0) {
        const char *text = getenv("QUADRA_AUDIO");
        value = text && text[0] == '0' ? 0 : 1;
    }
    return value;
}

/* Returns NOT_HANDLED when Darling should answer. out == 0 means size only. */
static OSStatus added_property(UInt32 object, const PropertyAddress *address, UInt32 *io_size, void *out) {
    if (!additions_enabled())
        return NOT_HANDLED;
    UInt32 selector = address->selector, scope = address->scope;
    if (is_device(object)) {
        switch (selector) {
        case FOURCC('s', 't', 'm', '#'): { /* streams */
            UInt32 stream = is_output_device(object) ? OUTPUT_STREAM : INPUT_STREAM;
            if (!device_has_stream(object, scope))
                return put(&stream, 0, io_size, out);
            return put_u32(stream, io_size, out);
        }
        case FOURCC('s', 'l', 'a', 'y'): { /* stream configuration */
            BufferList list = {0, {{0, 0, 0}}};
            if (!device_has_stream(object, scope) || scope == SCOPE_GLOBAL)
                return put(&list, 8, io_size, out);
            list.count = 1;
            list.buffers[0].channels = current_format.channels_per_frame;
            return put(&list, sizeof list, io_size, out);
        }
        case FOURCC('f', 's', 'i', 'z'): { /* buffer frame size, from Darling's byte size */
            UInt32 bytes = 0, size = sizeof bytes;
            PropertyAddress legacy = {FOURCC('b', 's', 'i', 'z'), scope, 0};
            if (AudioObjectGetPropertyData(object, &legacy, 0, 0, &size, &bytes) != NO_ERROR || !bytes)
                bytes = 512 * current_format.bytes_per_frame;
            return put_u32(bytes / current_format.bytes_per_frame, io_size, out);
        }
        case FOURCC('f', 's', 'z', '#'): { /* buffer frame size range */
            ValueRange range = {64, 4096};
            return put(&range, sizeof range, io_size, out);
        }
        case FOURCC('l', 't', 'n', 'c'): /* latency */
        case FOURCC('s', 'a', 'f', 't'): /* safety offset */
            return put_u32(0, io_size, out);
        case FOURCC('t', 'r', 'a', 'n'): /* transport type: built-in */
            return put_u32(FOURCC('b', 'l', 't', 'n'), io_size, out);
        case FOURCC('c', 'l', 'c', 'k'): /* clock domain */
            return put_u32(0, io_size, out);
        }
        return NOT_HANDLED;
    }
    if (is_stream(object)) {
        switch (selector) {
        case FOURCC('s', 'f', 'm', 't'): /* virtual format */
        case FOURCC('p', 'f', 't', ' '): /* physical format */
            return put(&current_format, sizeof current_format, io_size, out);
        case FOURCC('s', 'f', 'm', 'a'): /* available virtual formats */
        case FOURCC('p', 'f', 't', 'a'): { /* available physical formats */
            RangedDescription ranged = {current_format, {current_format.sample_rate, current_format.sample_rate}};
            return put(&ranged, sizeof ranged, io_size, out);
        }
        case FOURCC('s', 'd', 'i', 'r'): /* direction: 0 output, 1 input */
            return put_u32(object == INPUT_STREAM, io_size, out);
        case FOURCC('s', 'c', 'h', 'n'): /* starting channel */
        case FOURCC('s', 'a', 'c', 't'): /* is active */
            return put_u32(1, io_size, out);
        case FOURCC('t', 'e', 'r', 'm'): /* terminal type */
        case FOURCC('l', 't', 'n', 'c'): /* latency */
            return put_u32(0, io_size, out);
        }
        return NOT_HANDLED;
    }
    return NOT_HANDLED;
}

/* ----------------------------------------------------------- interposers */

static OSStatus h_get(UInt32 object, const PropertyAddress *address, UInt32 qsize, const void *qdata,
                      UInt32 *size, void *data) {
    if (address) {
        UInt32 capacity = size ? *size : 0;
        OSStatus status = added_property(object, address, &capacity, data);
        if (status != NOT_HANDLED) {
            if (size) *size = capacity;
            report("GetPropertyData", object, address, status, capacity, 1);
            return status;
        }
    }
    OSStatus status = AudioObjectGetPropertyData(object, address, qsize, qdata, size, data);
    report("GetPropertyData", object, address, status, size ? *size : 0, 0);
    return status;
}
DYLD_INTERPOSE(h_get, AudioObjectGetPropertyData)

static OSStatus h_size(UInt32 object, const PropertyAddress *address, UInt32 qsize, const void *qdata,
                       UInt32 *size) {
    if (address) {
        UInt32 capacity = 0;
        OSStatus status = added_property(object, address, &capacity, 0);
        if (status != NOT_HANDLED) {
            if (size) *size = capacity;
            report("GetPropertyDataSize", object, address, status, capacity, 1);
            return status;
        }
    }
    OSStatus status = AudioObjectGetPropertyDataSize(object, address, qsize, qdata, size);
    report("GetPropertyDataSize", object, address, status, size ? *size : 0, 0);
    return status;
}
DYLD_INTERPOSE(h_size, AudioObjectGetPropertyDataSize)

static unsigned char h_has(UInt32 object, const PropertyAddress *address) {
    UInt32 capacity = 0;
    if (address && added_property(object, address, &capacity, 0) != NOT_HANDLED) {
        report("HasProperty", object, address, 1, 0, 1);
        return 1;
    }
    unsigned char has = AudioObjectHasProperty(object, address);
    report("HasProperty", object, address, has, 0, 0);
    return has;
}
DYLD_INTERPOSE(h_has, AudioObjectHasProperty)

static OSStatus h_set(UInt32 object, const PropertyAddress *address, UInt32 qsize, const void *qdata,
                      UInt32 size, const void *data) {
    if (additions_enabled() && address && is_stream(object) &&
        (address->selector == FOURCC('s', 'f', 'm', 't') || address->selector == FOURCC('p', 'f', 't', ' '))) {
        /* Only the format Darling's PulseAudio stream uses is accepted. */
        const StreamDescription *format = data;
        OSStatus status = size == sizeof *format && format->format_id == current_format.format_id &&
                                  format->sample_rate == current_format.sample_rate &&
                                  format->channels_per_frame == current_format.channels_per_frame &&
                                  format->bits_per_channel == 32 && (format->format_flags & 1)
                              ? NO_ERROR
                              : UNSUPPORTED_FORMAT;
        report("SetPropertyData", object, address, status, size, 1);
        return status;
    }
    if (additions_enabled() && address && is_device(object) &&
        address->selector == FOURCC('f', 's', 'i', 'z') && size == 4) {
        UInt32 bytes = *(const UInt32 *)data * current_format.bytes_per_frame;
        PropertyAddress legacy = {FOURCC('b', 's', 'i', 'z'), address->scope, 0};
        OSStatus status = AudioObjectSetPropertyData(object, &legacy, 0, 0, sizeof bytes, &bytes);
        report("SetPropertyData", object, address, status, size, 1);
        return status;
    }
    OSStatus status = AudioObjectSetPropertyData(object, address, qsize, qdata, size, data);
    report("SetPropertyData", object, address, status, size, 0);
    return status;
}
DYLD_INTERPOSE(h_set, AudioObjectSetPropertyData)

static OSStatus h_settable(UInt32 object, const PropertyAddress *address, unsigned char *settable) {
    if (additions_enabled() && address && ((is_stream(object) && (address->selector == FOURCC('s', 'f', 'm', 't') ||
                                           address->selector == FOURCC('p', 'f', 't', ' '))) ||
                    (is_device(object) && address->selector == FOURCC('f', 's', 'i', 'z')))) {
        if (settable) *settable = 1;
        return NO_ERROR;
    }
    UInt32 capacity = 0;
    if (address && added_property(object, address, &capacity, 0) != NOT_HANDLED) {
        if (settable) *settable = 0;
        return NO_ERROR;
    }
    return AudioObjectIsPropertySettable(object, address, settable);
}
DYLD_INTERPOSE(h_settable, AudioObjectIsPropertySettable)

/* Darling's AudioObjectAddPropertyListener always fails ("unknown
 * property"), and FMOD treats a failed listener registration (default device
 * changes and so on) as a failed init. Darling's devices never change, so
 * listeners are accepted and simply never called. */
static OSStatus h_add_listener(UInt32 object, const PropertyAddress *address, ListenerProc proc, void *data) {
    if (additions_enabled()) {
        report("AddPropertyListener", object, address, NO_ERROR, 0, 1);
        return NO_ERROR;
    }
    return AudioObjectAddPropertyListener(object, address, proc, data);
}
DYLD_INTERPOSE(h_add_listener, AudioObjectAddPropertyListener)

static OSStatus h_remove_listener(UInt32 object, const PropertyAddress *address, ListenerProc proc, void *data) {
    if (additions_enabled())
        return NO_ERROR;
    return AudioObjectRemovePropertyListener(object, address, proc, data);
}
DYLD_INTERPOSE(h_remove_listener, AudioObjectRemovePropertyListener)

/* ------------------------------------------------------- output unit */

/* Darling's AUHAL only accepts the canonical non-interleaved AudioUnit format
 * (the AUBase check), while FMOD asks for interleaved float and then gave up
 * (kAudioUnitErr_FormatNotSupported). Instead of it, FMOD gets this small
 * HAL output unit: it accepts FMOD's format and render callback, sets that
 * format on Darling's output device and feeds it from an IOProc, which
 * Darling plays through PulseAudio. */

typedef OSStatus (*RenderProc)(void *, UInt32 *, const void *, UInt32, UInt32, BufferList *);
typedef struct {
    Float64 sample_time;
    unsigned long long host_time;
    Float64 rate_scalar;
    unsigned long long word_clock;
    unsigned char smpte[24];
    UInt32 flags, reserved;
} TimeStamp;

#define UNIT_MAGIC 0x4d4f4241u /* 'MOBA' */
typedef struct {
    UInt32 magic;
    UInt32 device;
    int output_enabled;
    int running;
    int initialized;
    StreamDescription format;
    RenderProc render;
    void *render_context;
    void *ioproc;
    UInt32 max_frames;
    Float64 sample_time;
    float *scratch;
    UInt32 scratch_frames;
    /* FMOD renders on our own thread into this ring; Darling's IOProc only
     * copies out of it (see unit_render_thread). */
    unsigned char *ring;
    unsigned long ring_bytes;
    volatile unsigned long ring_written, ring_read;
    volatile int producing;
    void *thread;
    /* Read at start, not on the render thread (getenv races setenv). */
    char fifo_path[1024];
    long buffer_ms;
    /* The microphone (bus 1), see unit_capture_thread. */
    int input_enabled;
    StreamDescription input_format; /* what AudioUnitRender delivers */
    RenderProc input_callback;
    void *input_context;
    volatile int capturing;
    void *capture_thread;
    unsigned char *capture_ring; /* float32, interleaved */
    unsigned long capture_ring_bytes;
    volatile unsigned long capture_written, capture_read;
    Float64 input_sample_time;
    char input_fifo_path[1024];
} OutputUnit;

#define INVALID_PROPERTY (-10879)
#define PROPERTY_NOT_WRITABLE (-10865)

static void *hal_component;

static OutputUnit *as_unit(void *instance) {
    OutputUnit *unit = instance;
    return unit && unit->magic == UNIT_MAGIC ? unit : 0;
}

/* Darling runs its PulseAudio loop on a GCD worker thread, so calling FMOD's
 * render callback from the IOProc ran the whole FMOD mixer on that small,
 * fragile thread; the game crashed inside Darling's workqueue code about a
 * second after audio started. FMOD therefore renders here, on a thread with
 * an 8 MB stack, 512 frames at a time into a ring of about 8192 frames. */
#define RENDER_FRAMES 512
#define RING_FRAMES 8192
extern int pthread_create(void **, const void *, void *(*)(void *), void *);
extern int pthread_join(void *, void **);
extern int pthread_attr_init(void *);
extern int pthread_attr_setstacksize(void *, unsigned long);
extern void quadra_sleep_us(unsigned int); /* darling_fixes.c: no darlingserver request */

static UInt32 unit_frame_bytes(OutputUnit *unit) {
    UInt32 channels = unit->format.channels_per_frame ? unit->format.channels_per_frame : 2;
    UInt32 sample_bytes = unit->format.bits_per_channel / 8 ? unit->format.bits_per_channel / 8 : 4;
    return channels * sample_bytes;
}

/* Render `frames` frames into `out` as interleaved samples; FMOD's status. */
static OSStatus unit_render(OutputUnit *unit, unsigned char *out, UInt32 frames) {
    UInt32 channels = unit->format.channels_per_frame ? unit->format.channels_per_frame : 2;
    UInt32 sample_bytes = unit->format.bits_per_channel / 8 ? unit->format.bits_per_channel / 8 : 4;
    UInt32 frame_bytes = channels * sample_bytes;
    int planar = (unit->format.format_flags & 0x20) != 0; /* kAudioFormatFlagIsNonInterleaved */
    TimeStamp stamp = {unit->sample_time, mach_absolute_time(), 1.0, 0, {0}, 3 /* sample+host time */, 0};
    UInt32 flags = 0;
    OSStatus status = -1;
    if (unit->render && !planar) {
        BufferList list = {1, {{channels, frames * frame_bytes, out}}};
        status = unit->render(unit->render_context, &flags, &stamp, 0, frames, &list);
    } else if (unit->render && unit->scratch) {
        struct { UInt32 count; Buffer buffers[8]; } list = {0};
        list.count = channels > 8 ? 8 : channels;
        for (UInt32 c = 0; c < list.count; c++) {
            list.buffers[c].channels = 1;
            list.buffers[c].byte_size = frames * sample_bytes;
            list.buffers[c].data = (unsigned char *)unit->scratch + (unsigned long)c * frames * sample_bytes;
        }
        status = unit->render(unit->render_context, &flags, &stamp, 0, frames, (BufferList *)&list);
        for (UInt32 f = 0; f < frames; f++)
            for (UInt32 c = 0; c < list.count; c++)
                for (UInt32 b = 0; b < sample_bytes; b++)
                    out[(f * channels + c) * sample_bytes + b] =
                        ((unsigned char *)list.buffers[c].data)[f * sample_bytes + b];
    }
    if (status != NO_ERROR)
        for (UInt32 i = 0; i < frames * frame_bytes; i++) out[i] = 0;
    unit->sample_time += frames;
    return status;
}

static void *unit_render_thread(void *context) {
    OutputUnit *unit = context;
    UInt32 frame_bytes = unit_frame_bytes(unit);
    unsigned long chunk = (unsigned long)RENDER_FRAMES * frame_bytes;
    unsigned char *block = malloc(chunk);
    if (!block)
        return 0;
    while (unit->producing) {
        unsigned long used = unit->ring_written - unit->ring_read;
        if (unit->ring_bytes - used < chunk) {
            quadra_sleep_us(2000);
            continue;
        }
        unit_render(unit, block, RENDER_FRAMES);
        unsigned long position = unit->ring_written % unit->ring_bytes;
        for (unsigned long i = 0; i < chunk; i++)
            unit->ring[(position + i) % unit->ring_bytes] = block[i];
        __sync_synchronize();
        unit->ring_written += chunk;
    }
    free(block);
    return 0;
}

/* Preferred output: QUADRA_AUDIO_FIFO names a FIFO that the launcher plays
 * on the host with pw-cat (raw float32 stereo 44.1 kHz). Darling's own audio
 * path runs PulseAudio on GCD, and Darling's workqueue nests every work item
 * on the same thread stack until it overflows; with sound playing that took
 * a few seconds. Writing to a FIFO keeps Darling's CoreAudio, PulseAudio and
 * GCD out of the audio path entirely.
 *
 * The render thread calls FMOD for a block every 512 frames' time, as a
 * sound card does: FMOD mixes on its own thread, and blocks asked for in
 * bursts came back silent (heard as dropouts of 11-35 ms; pw-cat takes 40 ms
 * of sound at once, so filling the pipe back up at once meant 3-4 calls
 * within 3 ms). That pace is corrected by up to 5% to keep about 50 ms of
 * sound in the pipe on average (QUADRA_AUDIO_BUFFER_MS), measured with
 * FIONREAD through a direct Linux ioctl: pw-cat drains it at the pace of the
 * sound card's clock, so the delay stays the same all session. Pacing by mach_absolute_time instead, as
 * before, never saw pw-cat: every cycle pw-cat skipped stayed in the pipe as
 * extra delay (on the host, 80 ms of queued sound became 103 ms within 90 s)
 * and a sound card whose clock runs apart from the system clock (USB and
 * wireless headsets) slowly filled or drained the pipe. The wall clock stays
 * as the fallback when FIONREAD fails. The FIFO is written non-blocking: a
 * player that stopped reading must not block this thread, nor
 * AudioOutputUnitStop, which joins it. */
extern int open(const char *, int, ...);
extern long write(int, const void *, unsigned long);
extern int close(int);
extern int *__error(void);
extern int pthread_sigmask(int, const unsigned int *, unsigned int *);
extern int atoi(const char *);
extern int vsnprintf(char *, unsigned long, const char *, __builtin_va_list);
#define FIFO_AHEAD_FRAMES 2600
#define FIFO_BUFFER_MS 50
#define DARWIN_O_WRONLY 0x1
#define DARWIN_O_NONBLOCK 0x4
#define DARWIN_EINTR 4
#define DARWIN_EAGAIN 35

/* The pipe's capacity in frames after asking Linux for room for `wanted`
 * frames (F_SETPIPE_SZ, up to /proc/sys/fs/pipe-max-size, 1 MB by default,
 * for users); 0 if Linux does not say. A pipe holds 64 KB (186 ms) unless
 * enlarged, too little for a large QUADRA_AUDIO_BUFFER_MS. */
static long fifo_capacity_frames(int fd, UInt32 frame_bytes, long wanted) {
    long size;
    __asm__ volatile("syscall" : "=a"(size) : "a"(72L /* Linux fcntl */), "D"((long)fd), "S"(1032L /* F_GETPIPE_SZ */)
                     : "rcx", "r11", "memory");
    if (size > 0 && size / (long)frame_bytes < wanted) {
        long grown;
        __asm__ volatile("syscall" : "=a"(grown)
                         : "a"(72L), "D"((long)fd), "S"(1031L /* F_SETPIPE_SZ */), "d"(wanted * (long)frame_bytes)
                         : "rcx", "r11", "memory");
        if (grown > 0)
            size = grown;
    }
    return size > 0 ? size / (long)frame_bytes : 0;
}

/* Frames queued in the pipe behind `fd`, or -1 without FIONREAD. */
static long fifo_queued_frames(int fd, UInt32 frame_bytes) {
    int bytes = 0;
    long result;
    __asm__ volatile("syscall" : "=a"(result)
                     : "a"(16L /* Linux ioctl */), "D"((long)fd), "S"(0x541BL /* FIONREAD */), "d"(&bytes)
                     : "rcx", "r11", "memory");
    return result < 0 ? -1 : bytes / (long)frame_bytes;
}

/* Write all of `data` unless the player stops reading for 250 ms (the rest
 * is dropped) or the unit stops. Returns 0 when the FIFO has to be reopened. */
static int fifo_write(OutputUnit *unit, int fd, const unsigned char *data, unsigned long size) {
    unsigned long done = 0;
    int waited_ms = 0;
    while (done < size && unit->producing) {
        long written = write(fd, data + done, size - done);
        if (written > 0) {
            done += (unsigned long)written;
            waited_ms = 0;
        } else if (written < 0 && *__error() == DARWIN_EINTR) {
            continue;
        } else if (written < 0 && *__error() == DARWIN_EAGAIN) {
            if (waited_ms >= 250)
                return 1;
            quadra_sleep_us(2000);
            waited_ms += 2;
        } else {
            return 0;
        }
    }
    return 1;
}

/* Audio problems in the log (always on, rate-limited): the pipe ran dry
 * because this thread came late, FMOD took long to render, or the player
 * stopped reading. Silence with none of these comes from the player's side. */
__attribute__((format(printf, 1, 2)))
static void audio_event(const char *format, ...) {
    static volatile long events;
    long count = __sync_add_and_fetch(&events, 1);
    if (count > 40 && count % 100)
        return;
    char line[240];
    int length = snprintf(line, sizeof line, "[Quadra Audio] ");
    __builtin_va_list arguments;
    __builtin_va_start(arguments, format);
    int added = vsnprintf(line + length, sizeof line - (unsigned long)length - 1, format, arguments);
    __builtin_va_end(arguments);
    if (added < 0)
        return;
    length += added;
    if ((unsigned long)length > sizeof line - 2) /* cut to fit */
        length = (int)sizeof line - 2;
    line[length++] = '\n';
    write(2, line, (unsigned long)length);
}

/* Loudest of the last `count` samples (float32) of a block, in thousandths
 * of full scale: a sound cut off mid-wave ends loud, a finished one near 0. */
static unsigned long long tail_level(const unsigned char *block, unsigned long size, unsigned long count) {
    const float *samples = (const float *)block;
    unsigned long total = size / 4;
    float peak = 0;
    for (unsigned long i = total > count ? total - count : 0; i < total; i++) {
        float value = samples[i] < 0 ? -samples[i] : samples[i];
        if (value > peak)
            peak = value;
    }
    return (unsigned long long)(peak * 1000 + 0.5f);
}

static int block_is_silent(const unsigned char *block, unsigned long size) {
    const unsigned int *words = (const unsigned int *)block;
    for (unsigned long i = 0; i < size / 4; i++)
        if (words[i] & 0x7fffffffu) /* anything but +0.0 or -0.0 */
            return 0;
    return 1;
}

/* The render thread runs FMOD's mixer and has to deliver 512 frames every
 * 11.6 ms while the game keeps every core busy, so it asks for a better nice
 * value than the game's threads, as far as RLIMIT_NICE allows (direct Linux
 * setpriority on this thread). */
static void raise_render_priority(void) {
    long tid, current;
    __asm__ volatile("syscall" : "=a"(tid) : "a"(186L /* Linux gettid */) : "rcx", "r11", "memory");
    /* Linux getpriority returns 20 - nice. A thread already better off (a
     * tool such as gamemode reniced the game) keeps its value. */
    __asm__ volatile("syscall" : "=a"(current) : "a"(140L /* Linux getpriority */), "D"(0L), "S"(tid)
                     : "rcx", "r11", "memory");
    int nice_now = current > 0 ? 20 - (int)current : 0;
    static const int nice_values[] = {-11, -8, -5};
    for (unsigned i = 0; i < sizeof nice_values / sizeof nice_values[0] && nice_values[i] < nice_now; i++) {
        long result;
        __asm__ volatile("syscall" : "=a"(result)
                         : "a"(141L /* Linux setpriority */), "D"(0L /* PRIO_PROCESS */), "S"(tid),
                           "d"((long)nice_values[i])
                         : "rcx", "r11", "memory");
        if (result == 0)
            return;
    }
}

static void *unit_fifo_thread(void *context) {
    OutputUnit *unit = context;
    const char *path = unit->fifo_path;
    raise_render_priority();
    /* A reader that went away must give EPIPE here, not kill the game. */
    unsigned int block_pipe = 1u << (13 - 1); /* SIGPIPE */
    pthread_sigmask(1 /* SIG_BLOCK */, &block_pipe, 0);
    UInt32 frame_bytes = unit_frame_bytes(unit);
    unsigned long chunk = (unsigned long)RENDER_FRAMES * frame_bytes;
    unsigned char *block = malloc(chunk);
    int fd = -1, by_fill = 0, player_stuck = 0, sounding = 0, silent_blocks = 0;
    unsigned long long full_since = 0, last_write = 0, last_render = 0, next_due = 0, cut_level = 0;
    unsigned long long start = mach_absolute_time();
    unsigned long long frames_written = 0;
    Float64 rate = unit->format.sample_rate > 0 ? unit->format.sample_rate : 44100.0;
    long target_ms = unit->buffer_ms > 0 ? unit->buffer_ms : FIFO_BUFFER_MS;
    if (target_ms < 15) target_ms = 15;
    if (target_ms > 500) target_ms = 500;
    long wanted_target = (long)(rate * target_ms / 1000), target = wanted_target;
    unsigned long long period = (unsigned long long)(RENDER_FRAMES * 1e9 / rate);
    double average = (double)target;
    while (block && unit->producing) {
        if (fd < 0) {
            fd = open(path, DARWIN_O_WRONLY | DARWIN_O_NONBLOCK);
            if (fd < 0) {
                quadra_sleep_us(200000);
                continue;
            }
            by_fill = fifo_queued_frames(fd, frame_bytes) >= 0;
            /* Twice the target must fit (a stopped player is noticed there),
             * plus a block. */
            long capacity = fifo_capacity_frames(fd, frame_bytes, 2 * wanted_target + 2 * RENDER_FRAMES);
            target = wanted_target;
            if (capacity && 2 * target + RENDER_FRAMES > capacity)
                target = (capacity - RENDER_FRAMES) / 2;
            average = (double)target;
            start = mach_absolute_time();
            frames_written = 0;
            if (tracing()) {
                char line[120];
                int length = snprintf(line, sizeof line, "[Quadra Audio] FIFO open, pacing by %s, %ld frames\n",
                                      by_fill ? "pipe fill" : "wall clock", by_fill ? target : FIFO_AHEAD_FRAMES);
                if (length > 0) write(2, line, (unsigned long)length);
            }
        }
        if (by_fill) {
            long queued = fifo_queued_frames(fd, frame_bytes);
            unsigned long long now = mach_absolute_time();
            if (queued >= 2 * target) {
                if (!full_since)
                    full_since = now;
                else if (!player_stuck && now - full_since > 1000000000ULL) {
                    player_stuck = 1;
                    if (last_write)
                        audio_event("the player stopped reading %llu ms ago (last block written %llu ms ago)",
                                    (now - full_since) / 1000000ULL, (now - last_write) / 1000000ULL);
                    else
                        audio_event("the player stopped reading %llu ms ago (before the first block)",
                                    (now - full_since) / 1000000ULL);
                }
                quadra_sleep_us(2000);
                continue;
            }
            if (player_stuck)
                audio_event("the player reads again after %llu ms (%llu frames were queued)",
                            (now - full_since) / 1000000ULL, (unsigned long long)queued);
            full_since = 0;
            player_stuck = 0;
            /* Not before the block is due, unless the pipe is nearly empty. */
            if (next_due && now < next_due && queued >= target / 3) {
                unsigned long long wait = (next_due - now) / 1000;
                quadra_sleep_us(wait < 2000 ? (unsigned int)wait : 2000);
                continue;
            }
            if (queued == 0 && last_write && now - last_write > 30000000ULL)
                audio_event("pipe ran dry: %llu ms since the last block (that render took %llu ms)",
                            (now - last_write) / 1000000ULL, last_render / 1000000ULL);
            /* The next block is due one period later, up to 5% sooner or
             * later to bring the pipe's average fill back to the target. */
            average += ((double)queued - average) / 16;
            double correction = 0.1 * (average - (double)target) / (double)target;
            correction = correction > 0.05 ? 0.05 : correction < -0.05 ? -0.05 : correction;
            if (!next_due || now > next_due + period)
                next_due = now;
            next_due += (unsigned long long)((double)period * (1 + correction));
        } else {
            double elapsed = (double)(mach_absolute_time() - start) / 1e9;
            double ahead = (double)frames_written - elapsed * rate;
            if (ahead > FIFO_AHEAD_FRAMES) {
                quadra_sleep_us(3000);
                continue;
            }
            if (ahead < -rate / 4) { /* fell far behind (stall): restart the clock */
                start = mach_absolute_time();
                frames_written = 0;
            }
        }
        unsigned long long before = mach_absolute_time();
        OSStatus status = unit_render(unit, block, RENDER_FRAMES);
        last_render = mach_absolute_time() - before;
        if (last_render > 20000000ULL)
            audio_event("FMOD took %llu ms to render %.1f ms of sound", last_render / 1000000ULL,
                        RENDER_FRAMES * 1000.0 / rate);
        if (status != NO_ERROR)
            audio_event("FMOD's render callback failed (status %d), block played as silence", (int)status);
        /* A dropout inside FMOD: one to three silent blocks (12-35 ms) between
         * sounding ones. Gaps in the game's own sound are rarely that short. */
        if (block_is_silent(block, chunk)) {
            if (sounding && ++silent_blocks > 3)
                sounding = 0;
        } else {
            if (sounding && silent_blocks)
                audio_event("FMOD rendered %d silent block(s) of %.1f ms between sounding ones; "
                            "the sound before was cut at level %llu/1000",
                            silent_blocks, RENDER_FRAMES * 1000.0 / rate, cut_level);
            sounding = 1;
            silent_blocks = 0;
            cut_level = tail_level(block, chunk, 64);
        }
        if (!fifo_write(unit, fd, block, chunk)) {
            close(fd);
            fd = -1;
            continue;
        }
        last_write = mach_absolute_time();
        frames_written += RENDER_FRAMES;
    }
    if (fd >= 0)
        close(fd);
    free(block);
    return 0;
}

static OSStatus unit_ioproc(UInt32 device, const void *now, const void *input, const void *input_time,
                            BufferList *output, const void *output_time, void *context) {
    (void)device; (void)now; (void)input; (void)input_time; (void)output_time;
    OutputUnit *unit = context;
    if (!output || !output->count)
        return NO_ERROR;
    Buffer *buffer = &output->buffers[0];
    UInt32 frame_bytes = unit_frame_bytes(unit);
    unsigned long wanted = (buffer->byte_size / frame_bytes) * frame_bytes;
    buffer->byte_size = (UInt32)wanted;
    unsigned char *bytes = buffer->data;
    __sync_synchronize();
    unsigned long available = unit->ring_written - unit->ring_read;
    unsigned long copied = available < wanted ? available : wanted;
    unsigned long position = unit->ring_read % unit->ring_bytes;
    for (unsigned long i = 0; i < copied; i++)
        bytes[i] = unit->ring[(position + i) % unit->ring_bytes];
    for (unsigned long i = copied; i < wanted; i++)
        bytes[i] = 0; /* underrun: silence */
    unit->ring_read += copied;
    return NO_ERROR; /* an error or 0 bytes would pause Darling's stream */
}

static void unit_stop_producer(OutputUnit *unit) {
    if (unit->producing) {
        unit->producing = 0;
        pthread_join(unit->thread, 0);
    }
}

/* The microphone (voice chat). Roblox's voice code drives an AUHAL unit the
 * way WebRTC does: input enabled on bus 1, an input callback, and inside
 * that callback AudioUnitRender pulls the captured frames. The launcher
 * records with pw-cat into QUADRA_AUDIO_INPUT_FIFO as float32 at the
 * rate and channel count the client asked for, but only while the request
 * file next to the FIFO exists (written at start here, removed at stop, so
 * the microphone is open only while the game listens). A thread reads
 * 10 ms blocks into a ring and calls the client's input callback for each. */
#define CAPTURE_RING_FRAMES 8192
#define DARWIN_O_RDONLY 0x0
#define DARWIN_O_CREAT 0x200
#define DARWIN_O_TRUNC 0x400
#define NO_CONNECTION (-10877) /* kAudioUnitErr_NoConnection */
extern long read(int, void *, unsigned long);
extern int unlink(const char *);

static UInt32 capture_channels(OutputUnit *unit) {
    UInt32 channels = unit->input_format.channels_per_frame;
    return channels >= 1 && channels <= 2 ? channels : 1;
}

static Float64 capture_rate(OutputUnit *unit) {
    Float64 rate = unit->input_format.sample_rate;
    return rate >= 8000 && rate <= 192000 ? rate : 48000;
}

static void capture_request_path(OutputUnit *unit, char *out, unsigned long size) {
    snprintf(out, size, "%s.request", unit->input_fifo_path);
}

static void *unit_capture_thread(void *context) {
    OutputUnit *unit = context;
    raise_render_priority();
    UInt32 channels = capture_channels(unit);
    UInt32 block_frames = (UInt32)(capture_rate(unit) / 100); /* 10 ms */
    unsigned long block_bytes = (unsigned long)block_frames * channels * 4;
    unsigned char *block = malloc(block_bytes);
    unsigned long filled = 0;
    int fd = -1;
    TimeStamp stamp = {0};
    while (block && unit->capturing) {
        if (fd < 0) {
            fd = open(unit->input_fifo_path, DARWIN_O_RDONLY | DARWIN_O_NONBLOCK);
            if (fd < 0) {
                quadra_sleep_us(200000);
                continue;
            }
        }
        long n = read(fd, block + filled, block_bytes - filled);
        if (n <= 0) { /* no recorder yet, or nothing new */
            quadra_sleep_us(5000);
            continue;
        }
        filled += (unsigned long)n;
        if (filled < block_bytes)
            continue;
        filled = 0;
        unsigned long position = unit->capture_written % unit->capture_ring_bytes;
        for (unsigned long i = 0; i < block_bytes; i++)
            unit->capture_ring[(position + i) % unit->capture_ring_bytes] = block[i];
        __sync_synchronize();
        unit->capture_written += block_bytes;
        if (unit->capture_written - unit->capture_read > unit->capture_ring_bytes)
            unit->capture_read = unit->capture_written - unit->capture_ring_bytes; /* the oldest go */
        stamp.sample_time = unit->input_sample_time;
        stamp.host_time = mach_absolute_time();
        stamp.flags = 0x3; /* sample time and host time valid */
        UInt32 flags = 0;
        if (unit->input_callback)
            unit->input_callback(unit->input_context, &flags, &stamp, 1, block_frames, 0);
        unit->input_sample_time += block_frames;
    }
    if (fd >= 0)
        close(fd);
    free(block);
    return 0;
}

static int unit_start_capture(OutputUnit *unit) {
    const char *fifo = getenv("QUADRA_AUDIO_INPUT_FIFO");
    if (unit->capturing)
        return 1;
    if (!fifo || !fifo[0] || __builtin_strlen(fifo) + 16 >= sizeof unit->input_fifo_path)
        return 0;
    __builtin_memcpy(unit->input_fifo_path, fifo, __builtin_strlen(fifo) + 1);
    UInt32 channels = capture_channels(unit);
    unit->capture_ring_bytes = (unsigned long)CAPTURE_RING_FRAMES * channels * 4;
    free(unit->capture_ring);
    unit->capture_ring = calloc(1, unit->capture_ring_bytes);
    if (!unit->capture_ring)
        return 0;
    unit->capture_written = unit->capture_read = 0;
    unit->input_sample_time = 0;
    char request[1100], text[64];
    capture_request_path(unit, request, sizeof request);
    int fd = open(request, DARWIN_O_WRONLY | DARWIN_O_CREAT | DARWIN_O_TRUNC, 0600);
    if (fd >= 0) {
        int length = snprintf(text, sizeof text, "%d %u\n", (int)capture_rate(unit), channels);
        if (length > 0) write(fd, text, (unsigned long)length);
        close(fd);
    }
    unit->capturing = 1;
    unsigned char attributes[64] = {0}; /* pthread_attr_t is 64 bytes on Darwin x86_64 */
    pthread_attr_init(attributes);
    pthread_attr_setstacksize(attributes, 8u << 20);
    if (pthread_create(&unit->capture_thread, attributes, unit_capture_thread, unit) != 0) {
        unit->capturing = 0;
        unlink(request);
        return 0;
    }
    report("input unit: microphone capture started", 0, 0, 0, 0, 1);
    return 1;
}

static void unit_stop_capture(OutputUnit *unit) {
    if (!unit->capturing)
        return;
    unit->capturing = 0;
    pthread_join(unit->capture_thread, 0);
    char request[1100];
    capture_request_path(unit, request, sizeof request);
    unlink(request);
    report("input unit: microphone capture stopped", 0, 0, 0, 0, 1);
}

/* AudioUnitRender on bus 1: the captured frames in the client's format. */
static OSStatus unit_render_input(OutputUnit *unit, UInt32 frames, BufferList *list) {
    if (!list || !list->count)
        return NO_CONNECTION;
    if (!unit->capturing)
        return NO_CONNECTION;
    const StreamDescription *format = &unit->input_format;
    UInt32 channels = capture_channels(unit);
    int non_interleaved = (format->format_flags & 0x20) != 0;
    int is_float = (format->format_flags & 0x1) != 0 && format->bits_per_channel == 32;
    int is_int16 = (format->format_flags & 0x4) != 0 && format->bits_per_channel == 16;
    if (!is_float && !is_int16)
        return -10868; /* kAudioUnitErr_FormatNotSupported */
    UInt32 sample_bytes = is_float ? 4 : 2;
    UInt32 per_buffer = non_interleaved ? 1 : channels;
    for (UInt32 b = 0; b < list->count; b++) {
        UInt32 capacity = list->buffers[b].byte_size / (sample_bytes * per_buffer);
        if (!list->buffers[b].data || capacity < frames)
            return -10851; /* kAudioUnitErr_InvalidPropertyValue: too small a buffer */
    }
    __sync_synchronize();
    unsigned long available = (unit->capture_written - unit->capture_read) / (channels * 4);
    UInt32 got = available < frames ? (UInt32)available : frames;
    unsigned long position = unit->capture_read % unit->capture_ring_bytes;
    for (UInt32 i = 0; i < frames; i++) {
        for (UInt32 c = 0; c < channels; c++) {
            float sample = 0;
            if (i < got) {
                unsigned char raw[4];
                unsigned long at = position + ((unsigned long)i * channels + c) * 4;
                for (int k = 0; k < 4; k++)
                    raw[k] = unit->capture_ring[(at + k) % unit->capture_ring_bytes];
                __builtin_memcpy(&sample, raw, 4);
            }
            Buffer *buffer = &list->buffers[non_interleaved ? (c < list->count ? c : list->count - 1) : 0];
            unsigned long index = non_interleaved ? i : (unsigned long)i * channels + c;
            if (is_float)
                ((float *)buffer->data)[index] = sample;
            else
                ((short *)buffer->data)[index] =
                    (short)((sample > 1 ? 1 : sample < -1 ? -1 : sample) * 32767);
        }
    }
    for (UInt32 b = 0; b < list->count; b++)
        list->buffers[b].byte_size = frames * sample_bytes * per_buffer;
    unit->capture_read += (unsigned long)got * channels * 4;
    return NO_ERROR;
}

static OSStatus t_render(void *instance, UInt32 *flags, const void *stamp, UInt32 element, UInt32 frames,
                         BufferList *list) {
    OutputUnit *unit = as_unit(instance);
    if (!unit)
        return AudioUnitRender(instance, flags, stamp, element, frames, list);
    return element == 1 ? unit_render_input(unit, frames, list) : NO_CONNECTION;
}
DYLD_INTERPOSE(t_render, AudioUnitRender)

static void unit_stop(OutputUnit *unit) {
    unit_stop_capture(unit);
    unit_stop_producer(unit);
    if (unit->running && unit->ioproc)
        AudioDeviceStop(unit->device, unit->ioproc);
    unit->running = 0;
    if (unit->ioproc) {
        AudioDeviceDestroyIOProcID(unit->device, unit->ioproc);
        unit->ioproc = 0;
    }
}

static void *t_find(void *after, const ComponentDescription *description) {
    void *component = AudioComponentFindNext(after, description);
    if (description && description->type == FOURCC('a', 'u', 'o', 'u') &&
        (description->subtype == FOURCC('a', 'h', 'a', 'l') ||
         description->subtype == FOURCC('d', 'e', 'f', ' ')))
        hal_component = component;
    if (tracing() && description) {
        char type[8], subtype[8], line[160];
        code(type, description->type);
        code(subtype, description->subtype);
        int length = snprintf(line, sizeof line, "[Quadra Audio] AudioComponentFindNext '%s'/'%s' -> %p\n",
                              type, subtype, component);
        if (length > 0) write(2, line, (unsigned long)length);
    }
    return component;
}
DYLD_INTERPOSE(t_find, AudioComponentFindNext)

static OSStatus t_new(void *component, void **instance) {
    if (additions_enabled() && component && component == hal_component && instance) {
        OutputUnit *unit = calloc(1, sizeof *unit);
        if (unit) {
            unit->magic = UNIT_MAGIC;
            unit->device = 2;
            unit->output_enabled = 1;
            unit->format = current_format;
            unit->input_format = current_format;
            unit->max_frames = 4096;
            *instance = unit;
            report("AudioComponentInstanceNew (shim output unit)", 0, 0, 0, 0, 1);
            return NO_ERROR;
        }
    }
    OSStatus status = AudioComponentInstanceNew(component, instance);
    report("AudioComponentInstanceNew", 0, 0, status, 0, 0);
    return status;
}
DYLD_INTERPOSE(t_new, AudioComponentInstanceNew)

static OSStatus t_dispose(void *instance) {
    OutputUnit *unit = as_unit(instance);
    if (unit) {
        unit_stop(unit);
        unit->magic = 0;
        free(unit->scratch);
        free(unit->ring);
        free(unit->capture_ring);
        free(unit);
        return NO_ERROR;
    }
    return AudioComponentInstanceDispose(instance);
}
DYLD_INTERPOSE(t_dispose, AudioComponentInstanceDispose)

static void report_format(const char *what, const StreamDescription *format) {
    if (!tracing() || !format)
        return;
    char id[8], line[220];
    code(id, format->format_id);
    int length = snprintf(line, sizeof line,
                          "[Quadra Audio]   %s format '%s' rate=%.0f flags=0x%x bytes/packet=%u frames/packet=%u "
                          "bytes/frame=%u channels=%u bits=%u\n",
                          what, id, format->sample_rate, format->format_flags, format->bytes_per_packet,
                          format->frames_per_packet, format->bytes_per_frame, format->channels_per_frame,
                          format->bits_per_channel);
    if (length > 0) write(2, line, (unsigned long)length);
}

static OSStatus unit_set(OutputUnit *unit, UInt32 id, UInt32 scope, UInt32 element, const void *data, UInt32 size) {
    switch (id) {
    case 2003: /* EnableIO */
        if (size >= 4 && scope == 2 && element == 0)
            unit->output_enabled = *(const UInt32 *)data != 0;
        if (size >= 4 && scope == 1 && element == 1)
            unit->input_enabled = *(const UInt32 *)data != 0;
        return NO_ERROR;
    case 2005: /* SetInputCallback */
        if (size < 2 * sizeof(void *)) return BAD_SIZE;
        unit->input_callback = ((RenderProc const *)data)[0];
        unit->input_context = ((void *const *)data)[1];
        return NO_ERROR;
    case 2000: /* CurrentDevice */
        if (size < 4) return BAD_SIZE;
        unit->device = *(const UInt32 *)data;
        return NO_ERROR;
    case 8: { /* StreamFormat */
        if (size != sizeof(StreamDescription)) return BAD_SIZE;
        const StreamDescription *format = data;
        report_format("output unit set", format);
        if (format->format_id != FOURCC('l', 'p', 'c', 'm'))
            return -10868; /* kAudioUnitErr_FormatNotSupported */
        if (scope == 1 && element == 0) /* what the client renders */
            unit->format = *format;
        else if (scope == 2 && element == 1) /* what the client records */
            unit->input_format = *format;
        return NO_ERROR;
    }
    case 23: /* SetRenderCallback */
        if (size < 2 * sizeof(void *)) return BAD_SIZE;
        unit->render = ((RenderProc const *)data)[0];
        unit->render_context = ((void *const *)data)[1];
        return NO_ERROR;
    case 14: /* MaximumFramesPerSlice */
        if (size >= 4) unit->max_frames = *(const UInt32 *)data;
        return NO_ERROR;
    }
    return NO_ERROR; /* accept and ignore anything else */
}

static OSStatus unit_get(OutputUnit *unit, UInt32 id, UInt32 scope, UInt32 element, void *data, UInt32 *size) {
    switch (id) {
    case 8: /* StreamFormat: the client side and the device side use the same format */
        return put(element == 1 ? &unit->input_format : &unit->format, sizeof unit->format, size, data);
    case 2000:
        return put_u32(unit->device, size, data);
    case 2003:
        return put_u32(scope == 2 ? (UInt32)unit->output_enabled
                                  : element == 1 ? (UInt32)unit->input_enabled : 0, size, data);
    case 2001: /* IsRunning */
        return put_u32((UInt32)(unit->running || unit->capturing), size, data);
    case 2006: /* HasIO: the output, and the microphone on bus 1 */
        return put_u32(1, size, data);
    case 14:
        return put_u32(unit->max_frames, size, data);
    case 12: { /* Latency */
        Float64 zero = 0;
        return put(&zero, sizeof zero, size, data);
    }
    }
    return INVALID_PROPERTY;
}

static OSStatus t_unit_set(void *instance, UInt32 id, UInt32 scope, UInt32 element, const void *data, UInt32 size) {
    OutputUnit *unit = as_unit(instance);
    OSStatus status = unit ? unit_set(unit, id, scope, element, data, size)
                           : AudioUnitSetProperty(instance, id, scope, element, data, size);
    if (tracing()) {
        char line[160];
        int length = snprintf(line, sizeof line, "[Quadra Audio] AudioUnitSetProperty id=%u scope=%u element=%u -> %d%s\n",
                              id, scope, element, status, unit ? " (shim)" : "");
        if (length > 0) write(2, line, (unsigned long)length);
    }
    return status;
}
DYLD_INTERPOSE(t_unit_set, AudioUnitSetProperty)

static OSStatus t_unit_get(void *instance, UInt32 id, UInt32 scope, UInt32 element, void *data, UInt32 *size) {
    OutputUnit *unit = as_unit(instance);
    OSStatus status = unit ? unit_get(unit, id, scope, element, data, size)
                           : AudioUnitGetProperty(instance, id, scope, element, data, size);
    if (tracing()) {
        char line[160];
        int length = snprintf(line, sizeof line, "[Quadra Audio] AudioUnitGetProperty id=%u scope=%u element=%u -> %d%s\n",
                              id, scope, element, status, unit ? " (shim)" : "");
        if (length > 0) write(2, line, (unsigned long)length);
    }
    return status;
}
DYLD_INTERPOSE(t_unit_get, AudioUnitGetProperty)

static OSStatus t_init(void *instance) {
    OutputUnit *unit = as_unit(instance);
    if (unit) {
        unit->initialized = 1;
        return NO_ERROR;
    }
    OSStatus status = AudioUnitInitialize(instance);
    report("AudioUnitInitialize", 0, 0, status, 0, 0);
    return status;
}
DYLD_INTERPOSE(t_init, AudioUnitInitialize)

static OSStatus t_uninit(void *instance) {
    OutputUnit *unit = as_unit(instance);
    if (unit) {
        unit_stop(unit);
        unit->initialized = 0;
        return NO_ERROR;
    }
    return AudioUnitUninitialize(instance);
}
DYLD_INTERPOSE(t_uninit, AudioUnitUninitialize)

static OSStatus t_start(void *instance) {
    OutputUnit *unit = as_unit(instance);
    if (!unit) {
        OSStatus status = AudioOutputUnitStart(instance);
        report("AudioOutputUnitStart", 0, 0, status, 0, 0);
        return status;
    }
    if (unit->input_enabled && unit->input_callback)
        unit_start_capture(unit);
    /* An input-only unit (voice chat) has no render callback: nothing to play. */
    if (unit->running || !unit->output_enabled || !unit->render)
        return NO_ERROR;
    const char *fifo = getenv("QUADRA_AUDIO_FIFO");
    if (fifo && fifo[0] && __builtin_strlen(fifo) < sizeof unit->fifo_path) {
        __builtin_memcpy(unit->fifo_path, fifo, __builtin_strlen(fifo) + 1);
        const char *buffer_ms = getenv("QUADRA_AUDIO_BUFFER_MS");
        unit->buffer_ms = buffer_ms && buffer_ms[0] ? atoi(buffer_ms) : 0;
        if ((unit->format.format_flags & 0x20) && !unit->scratch)
            unit->scratch = malloc((unsigned long)RENDER_FRAMES * unit_frame_bytes(unit));
        unit->producing = 1;
        unsigned char attributes[64] = {0}; /* pthread_attr_t is 64 bytes on Darwin x86_64 */
        pthread_attr_init(attributes);
        pthread_attr_setstacksize(attributes, 8u << 20);
        if (pthread_create(&unit->thread, attributes, unit_fifo_thread, unit) != 0) {
            unit->producing = 0;
            return -1;
        }
        unit->running = 1;
        report("output unit: start (host FIFO)", 0, 0, 0, 0, 1);
        return NO_ERROR;
    }
    /* Darling's device takes the stream format through the legacy
     * kAudioDevicePropertyStreamFormat ('sfmt') and wants it interleaved;
     * a non-interleaved client format is interleaved in the IOProc. */
    StreamDescription device_format = unit->format;
    if (device_format.format_flags & 0x20) {
        device_format.format_flags &= ~0x20u;
        device_format.bytes_per_frame = device_format.channels_per_frame * (device_format.bits_per_channel / 8);
        device_format.bytes_per_packet = device_format.bytes_per_frame;
    }
    UInt32 frame_bytes = unit_frame_bytes(unit);
    if (!unit->ring) {
        unit->ring_bytes = (unsigned long)RING_FRAMES * frame_bytes;
        unit->ring = calloc(1, unit->ring_bytes);
    }
    if ((unit->format.format_flags & 0x20) && !unit->scratch)
        unit->scratch = malloc((unsigned long)RENDER_FRAMES * frame_bytes);
    if (!unit->ring)
        return -1;
    unit->ring_written = unit->ring_read = 0;
    unit->producing = 1;
    unsigned char attributes[64] = {0}; /* pthread_attr_t is 64 bytes on Darwin x86_64 */
    pthread_attr_init(attributes);
    pthread_attr_setstacksize(attributes, 8u << 20);
    if (pthread_create(&unit->thread, attributes, unit_render_thread, unit) != 0) {
        unit->producing = 0;
        return -1;
    }
    PropertyAddress format_address = {FOURCC('s', 'f', 'm', 't'), SCOPE_OUTPUT, 0};
    OSStatus status = AudioObjectSetPropertyData(unit->device, &format_address, 0, 0,
                                                 sizeof device_format, &device_format);
    report("output unit: device format", unit->device, &format_address, status, 0, 1);
    /* A unit started again after a stop keeps its IOProc. */
    status = unit->ioproc ? NO_ERROR : AudioDeviceCreateIOProcID(unit->device, (void *)unit_ioproc, unit, &unit->ioproc);
    if (status == NO_ERROR)
        status = AudioDeviceStart(unit->device, unit->ioproc);
    unit->running = status == NO_ERROR;
    if (!unit->running)
        unit_stop(unit); /* the render thread would call FMOD with nobody playing */
    report("output unit: start", unit->device, 0, status, 0, 1);
    return status;
}
DYLD_INTERPOSE(t_start, AudioOutputUnitStart)

static OSStatus t_stop(void *instance) {
    OutputUnit *unit = as_unit(instance);
    if (unit) {
        unit_stop_capture(unit);
        unit_stop_producer(unit);
        if (unit->running && unit->ioproc)
            AudioDeviceStop(unit->device, unit->ioproc);
        unit->running = 0;
        return NO_ERROR;
    }
    return AudioOutputUnitStop(instance);
}
DYLD_INTERPOSE(t_stop, AudioOutputUnitStop)

static OSStatus t_ioproc(UInt32 device, void *proc, void *data, void **id) {
    OSStatus status = AudioDeviceCreateIOProcID(device, proc, data, id);
    report("AudioDeviceCreateIOProcID", device, 0, status, 0, 0);
    return status;
}
DYLD_INTERPOSE(t_ioproc, AudioDeviceCreateIOProcID)

static OSStatus t_dstart(UInt32 device, void *proc) {
    OSStatus status = AudioDeviceStart(device, proc);
    report("AudioDeviceStart", device, 0, status, 0, 0);
    return status;
}
DYLD_INTERPOSE(t_dstart, AudioDeviceStart)

/* Host time: Darling's AudioGetCurrentHostTime is a stub (logs "STUB" and
 * returns nothing useful), and FMOD times its mixing with it. Darling's
 * mach_absolute_time counts nanoseconds, so host time is nanoseconds too. */
W unsigned long long AudioGetCurrentHostTime(void);
W Float64 AudioGetHostClockFrequency(void);
W unsigned long long AudioConvertNanosToHostTime(unsigned long long);

static unsigned long long h_host_time(void) {
    return mach_absolute_time();
}
DYLD_INTERPOSE(h_host_time, AudioGetCurrentHostTime)

static Float64 h_host_frequency(void) {
    return 1000000000.0;
}
DYLD_INTERPOSE(h_host_frequency, AudioGetHostClockFrequency)

static unsigned long long h_nanos_to_host(unsigned long long nanos) {
    return nanos;
}
DYLD_INTERPOSE(h_nanos_to_host, AudioConvertNanosToHostTime)
