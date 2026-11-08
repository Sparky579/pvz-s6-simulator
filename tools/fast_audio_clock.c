/* Deterministic DirectSound peripheral clock, not a replacement Foley system.
 * The original game still chooses samples, pitch, suppression, channels and
 * random calls. Only tracked sample-buffer playback time follows game ticks.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <mmsystem.h>
#include <dsound.h>
#include <stdint.h>
#include <stdlib.h>

typedef HRESULT (WINAPI *StatusFn)(void *,DWORD *);
typedef HRESULT (WINAPI *PlayFn)(void *,DWORD,DWORD,DWORD);
typedef HRESULT (WINAPI *SetFn)(void *,DWORD);
typedef HRESULT (WINAPI *StopFn)(void *);
typedef ULONG (WINAPI *ReleaseFn)(void *);
typedef HRESULT (WINAPI *CursorFn)(void*,DWORD*,DWORD*);
typedef struct VTable {
    void **address;
    StatusFn status;
    PlayFn play;
    SetFn position,frequency;
    StopFn stop;
    ReleaseFn release;
    CursorFn cursor;
} VTable;
typedef struct Buffer {
    void *object;
    uint64_t position,limit; /* sample frames multiplied by 100 */
    DWORD tick,frequency,block_align;
    BOOL playing,looping;
    struct Buffer *next;
} Buffer;

static VTable tables[8];
static unsigned table_count;
static Buffer *buffers[1024];
static CRITICAL_SECTION guard;
static volatile DWORD *game_tick;
static DWORD WINAPI sound_milliseconds(void) { return *game_tick*10u; }
void *s6_original_play;
__declspec(dllexport) volatile DWORD S6AudioError;
__declspec(dllexport) volatile DWORD S6AudioBuffers;
__declspec(dllexport) DWORD S6AudioPhysicalOutput;
/* Prototype only: a declared healthy virtual device can answer its tracked
 * playback state without entering Wine's real audio backend on every poll. */
__declspec(dllexport) DWORD S6AudioBackendValidation=1;

static unsigned bucket(void *object) { return (((uintptr_t)object)>>4)&1023; }
static Buffer *find_buffer(void *object) {
    Buffer *b=buffers[bucket(object)];
    while(b && b->object!=object)b=b->next;
    return b;
}
static VTable *find_table(void *object) {
    void **v=*(void***)object;
    for(unsigned i=0;i<table_count;i++)if(tables[i].address==v)return &tables[i];
    return NULL;
}
static void advance(Buffer *b) {
    DWORD tick=*game_tick,elapsed=tick-b->tick;
    b->tick=tick;
    if(!b->playing)return;
    b->position+=(uint64_t)elapsed*b->frequency;
    if(b->limit && b->position>=b->limit) {
        if(b->looping)b->position%=b->limit;
        else { b->position=b->limit;b->playing=FALSE; }
    }
}
static HRESULT WINAPI status_hook(void *object,DWORD *status) {
    VTable *t=find_table(object);
    if(!S6AudioBackendValidation && !S6AudioPhysicalOutput && status) {
        EnterCriticalSection(&guard);
        Buffer *b=find_buffer(object);
        if(b) {
            advance(b);*status=b->playing?DSBSTATUS_PLAYING:0;
            if(b->playing && b->looping)*status|=DSBSTATUS_LOOPING;
            LeaveCriticalSection(&guard);return DS_OK;
        }
        LeaveCriticalSection(&guard);
    }
    HRESULT hr=t->status(object,status);
    if(FAILED(hr))return hr;
    EnterCriticalSection(&guard);
    Buffer *b=find_buffer(object);
    if(b) {
        advance(b);
        *status&=~(DSBSTATUS_PLAYING|DSBSTATUS_LOOPING);
        if(b->playing)*status|=DSBSTATUS_PLAYING;
        if(b->playing && b->looping)*status|=DSBSTATUS_LOOPING;
    }
    LeaveCriticalSection(&guard);
    return hr;
}
static HRESULT WINAPI play_hook(void *object,DWORD reserved,DWORD priority,DWORD flags) {
    VTable *t=find_table(object);
    EnterCriticalSection(&guard);
    BOOL tracked=find_buffer(object)!=NULL;
    LeaveCriticalSection(&guard);
    HRESULT hr;
    if(tracked && !S6AudioPhysicalOutput && reserved==0 && priority==0 && !(flags&~DSBPLAY_LOOPING)) {
        DWORD status=0;hr=S6AudioBackendValidation?t->status(object,&status):DS_OK;
        if(SUCCEEDED(hr) && (status&DSBSTATUS_BUFFERLOST))hr=DSERR_BUFFERLOST;
    } else hr=t->play(object,reserved,priority,flags);
    if(SUCCEEDED(hr)) {
        EnterCriticalSection(&guard);
        Buffer *b=find_buffer(object);
        if(b) { advance(b);b->tick=*game_tick;b->playing=TRUE;b->looping=(flags&DSBPLAY_LOOPING)!=0; }
        LeaveCriticalSection(&guard);
    }
    return hr;
}
static HRESULT WINAPI cursor_hook(void *object,DWORD *play,DWORD *write) {
    VTable *t=find_table(object);
    HRESULT hr=t->cursor(object,play,write);
    if(FAILED(hr))return hr;
    EnterCriticalSection(&guard);
    Buffer *b=find_buffer(object);
    if(b && play) {
        advance(b);
        uint64_t position=b->position;
        if(b->limit)position%=b->limit;
        *play=(DWORD)(position/100)*b->block_align;
    }
    LeaveCriticalSection(&guard);
    return hr;
}
static HRESULT WINAPI stop_hook(void *object) {
    VTable *t=find_table(object);
    HRESULT hr=t->stop(object);
    if(SUCCEEDED(hr)) {
        EnterCriticalSection(&guard);
        Buffer *b=find_buffer(object);if(b) {advance(b);b->playing=FALSE;}
        LeaveCriticalSection(&guard);
    }
    return hr;
}
static HRESULT WINAPI position_hook(void *object,DWORD position) {
    VTable *t=find_table(object);
    HRESULT hr=t->position(object,position);
    if(SUCCEEDED(hr)) {
        EnterCriticalSection(&guard);
        Buffer *b=find_buffer(object);
        if(b) {b->position=(uint64_t)(position/b->block_align)*100;b->tick=*game_tick;}
        LeaveCriticalSection(&guard);
    }
    return hr;
}
static HRESULT WINAPI frequency_hook(void *object,DWORD frequency) {
    VTable *t=find_table(object);
    HRESULT hr=t->frequency(object,frequency);
    if(SUCCEEDED(hr)) {
        typedef HRESULT (WINAPI *GetFrequency)(void*,DWORD*);
        DWORD actual=0;
        HRESULT got=((GetFrequency)(t->address[8]))(object,&actual);
        if(FAILED(got)) {S6AudioError=got;return hr;}
        EnterCriticalSection(&guard);
        Buffer *b=find_buffer(object);if(b) {advance(b);b->frequency=actual;}
        LeaveCriticalSection(&guard);
    }
    return hr;
}
static ULONG WINAPI release_hook(void *object) {
    VTable *t=find_table(object);
    ULONG count=t->release(object);
    if(!count) {
        EnterCriticalSection(&guard);
        Buffer **p=&buffers[bucket(object)];
        while(*p && (*p)->object!=object)p=&(*p)->next;
        if(*p) {Buffer *old=*p;*p=old->next;free(old);}
        LeaveCriticalSection(&guard);
    }
    return count;
}

static BOOL install_table(void *object) {
    if(find_table(object))return TRUE;
    if(table_count==8) {S6AudioError=ERROR_TOO_MANY_NAMES;return FALSE;}
    void **v=*(void***)object;
    VTable *t=&tables[table_count];
    t->address=v;t->release=(ReleaseFn)v[2];t->status=(StatusFn)v[9];
    t->cursor=(CursorFn)v[4];
    t->play=(PlayFn)v[12];t->position=(SetFn)v[13];t->frequency=(SetFn)v[17];t->stop=(StopFn)v[18];
    DWORD old;
    if(!VirtualProtect(v,21*sizeof(void*),PAGE_EXECUTE_READWRITE,&old)) {S6AudioError=GetLastError();return FALSE;}
    table_count++;
    v[2]=release_hook;v[4]=cursor_hook;v[9]=status_hook;v[12]=play_hook;v[13]=position_hook;
    v[17]=frequency_hook;v[18]=stop_hook;
    DWORD ignored;VirtualProtect(v,21*sizeof(void*),old,&ignored);
    return TRUE;
}

void __cdecl s6_register_instance(void *instance) {
    void *object=*(void**)((char*)instance+0xc);
    if(!object)return;
    if(!S6AudioBackendValidation) {
        EnterCriticalSection(&guard);
        BOOL registered=find_buffer(object)!=NULL;
        LeaveCriticalSection(&guard);
        if(registered)return;
    }
    void **v=*(void***)object;
    typedef HRESULT (WINAPI *CapsFn)(void*,DSBCAPS*);
    typedef HRESULT (WINAPI *FormatFn)(void*,WAVEFORMATEX*,DWORD,DWORD*);
    typedef HRESULT (WINAPI *FrequencyFn)(void*,DWORD*);
    DSBCAPS caps={0};caps.dwSize=sizeof(caps);
    WAVEFORMATEX format={0};DWORD frequency=0;
    HRESULT hr=((CapsFn)v[3])(object,&caps);
    if(SUCCEEDED(hr))hr=((FormatFn)v[5])(object,&format,sizeof(format),NULL);
    if(SUCCEEDED(hr))hr=((FrequencyFn)v[8])(object,&frequency);
    if(FAILED(hr) || !format.nBlockAlign || !frequency) {S6AudioError=FAILED(hr)?hr:ERROR_INVALID_DATA;return;}
    EnterCriticalSection(&guard);
    if(!install_table(object)) {LeaveCriticalSection(&guard);return;}
    Buffer *b=find_buffer(object);
    if(!b) {
        b=calloc(1,sizeof(*b));
        if(!b) {S6AudioError=ERROR_OUTOFMEMORY;LeaveCriticalSection(&guard);return;}
        b->object=object;unsigned i=bucket(object);b->next=buffers[i];buffers[i]=b;
        S6AudioBuffers++;
    }
    b->limit=(uint64_t)(caps.dwBufferBytes/format.nBlockAlign)*100;
    b->block_align=format.nBlockAlign;b->frequency=frequency;b->tick=*game_tick;
    LeaveCriticalSection(&guard);
}

__attribute__((naked)) static void game_play_hook(void) {
    __asm__ __volatile__(
        "pushfd\n pushad\n mov ebp,esp\n sub esp,528\n and esp,-16\n"
        "fxsave [esp]\n push ecx\n call _s6_register_instance\n add esp,4\n"
        "fxrstor [esp]\n mov esp,ebp\n popad\n popfd\n jmp DWORD PTR [_s6_original_play]\n");
}

__declspec(dllexport) DWORD WINAPI S6AudioInit(void *app) {
    void **play=(void**)0x675fbc;
    unsigned char *cleanup_clock=(unsigned char*)0x5c5922;
    const unsigned char expected_clock[]={0xff,0x15,0x8c,0x20,0x65,0x00};
    if(*play==(void*)game_play_hook)return 0;
    if(*play!=(void*)0x5c7e20)return ERROR_INVALID_DATA;
    if(memcmp(cleanup_clock,expected_clock,sizeof(expected_clock)))return ERROR_INVALID_DATA;
    InitializeCriticalSection(&guard);
    game_tick=(volatile DWORD*)((char*)app+0x484);
    s6_original_play=*play;
    DWORD old;
    if(!VirtualProtect(play,4,PAGE_EXECUTE_READWRITE,&old))return GetLastError();
    *play=game_play_hook;
    DWORD ignored;VirtualProtect(play,4,old,&ignored);
    /* The original channel allocator also checks GetTickCount to release
     * finished instances every second. Keep its exact cleanup algorithm;
     * provide the same device timeline used by the sample buffers. */
    if(!VirtualProtect(cleanup_clock,6,PAGE_EXECUTE_READWRITE,&old))return GetLastError();
    int32_t relative=(int32_t)((uintptr_t)sound_milliseconds-(uintptr_t)(cleanup_clock+5));
    cleanup_clock[0]=0xe8;memcpy(cleanup_clock+1,&relative,4);cleanup_clock[5]=0x90;
    VirtualProtect(cleanup_clock,6,old,&ignored);
    FlushInstructionCache(GetCurrentProcess(),cleanup_clock,6);
    return 0;
}
